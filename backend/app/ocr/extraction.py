"""The OCR worker's write-back logic (design D127) — `process()` is the
single function `app.ocr_worker.handler` calls per S3 record. Runs
entirely on a direct `SessionLocal` session with NO `WorkspaceScope` and
NO HTTP request context (design D125): this is a trusted, internal
process acting on a key it already parsed from an S3 event, not a
member-scoped read.

Order of operations, all inside one caller-owned transaction per record:
1. `SELECT ... FOR UPDATE` the transaction row, scoped to
   `(id, workspace_id, ocr_status='pending_ocr')` — not found means
   already processed, wrong workspace, deleted, or never a draft, and is
   a safe no-op (design's idempotency/replay guard). A first-attempt miss
   additionally retries once after a 2s sleep (design D130's
   commit-visibility race) before giving up.
2. Call Textract (`app.ocr.textract`), classify the three-way failure
   taxonomy (design D128/D129).
3. Upsert `transaction_ocr_extraction` (design D117's `ON CONFLICT
   (transaction_id) DO UPDATE`).
4. Set `photo_content_type`/`photo_uploaded_at` from S3's own object
   metadata — the browser's direct presigned-POST upload never goes
   through `confirm_photo_upload`, so this is the only place those two
   columns are ever written for a photo-first transaction (the existing
   `ck_transaction_photo_pair` CHECK requires them written together).
5. The single conditional `UPDATE ... WHERE ocr_status = 'pending_ocr'`
   transition to `'extracted'` or `'extraction_failed'` (design D116) —
   the same statement that makes a duplicate/replayed invocation of an
   already-finished record a no-op on its NEXT run, because step 1 will
   no longer find `ocr_status='pending_ocr'`.
6. `process()` itself commits — one session PER RECORD (design D125), so
   one poisoned record's rollback (an unhandled exception before this
   point) can never touch a sibling record's already-committed work.
   `app.ocr_worker.handler` opens and closes that session; it never calls
   `commit()`/`rollback()` itself.
"""

from __future__ import annotations

import datetime
import time
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.ocr import textract
from app.transactions.models import OcrStatus, Transaction
from app.transactions.ocr_models import TransactionOcrExtraction

# Design D130: a single bounded re-read on a first-attempt miss, not a
# raise-and-let-Lambda-retry (ruled out by design D129 — Lambda's own
# async retry is disabled and is invisible to this code anyway).
_NOT_FOUND_RETRY_DELAY_SECONDS = 2.0


def _lock_pending_draft(
    db: Session, *, workspace_id: uuid.UUID, transaction_id: uuid.UUID
) -> Transaction | None:
    """Deliberately uses the legacy `Session.query()` API rather than
    `sa.select(Transaction)` — this worker-internal, primary-key-scoped
    row lock is NOT a visibility query and has no relationship to
    `visible_transactions`/`ocr_draft_transactions` at all, so it must
    stay outside design D120/D121's "exactly one file" structural
    invariant on `app/transactions/queries.py` rather than becoming a
    third, competing `sa.select(Transaction)` call site elsewhere in the
    backend."""
    return (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id)
        .filter(Transaction.workspace_id == workspace_id)
        .filter(Transaction.ocr_status == OcrStatus.PENDING_OCR)
        .with_for_update()
        .one_or_none()
    )


def _upsert_extraction(
    db: Session, *, transaction_id: uuid.UUID, result: textract.ExtractionResult
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    values = {
        "transaction_id": transaction_id,
        "status": result.status,
        "failure_reason": result.failure_reason,
        "extracted_amount": result.extracted_amount,
        "extracted_occurred_on": result.extracted_occurred_on,
        "extracted_vendor_name": result.extracted_vendor_name,
        "extracted_currency": result.extracted_currency,
        "field_confidence": result.field_confidence,
        # Design D117's privacy rule: `raw_response` is stored for
        # debugging via direct DB access ONLY — never logged, never
        # fixtured, never returned by any API response.
        "raw_response": result.raw_response,
        "attempt_count": result.attempt_count,
        "created_at": now,
    }
    stmt = pg_insert(TransactionOcrExtraction).values(**values)
    update_columns = {
        column: stmt.excluded[column] for column in values if column != "transaction_id"
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=[TransactionOcrExtraction.transaction_id],
        set_=update_columns,
    )
    db.execute(stmt)


def _run_textract(*, bucket: str, key: str) -> textract.ExtractionResult:
    """Design D128/D129: runs the retrying Textract call and classifies
    every outcome (retries-exhausted, non-retryable, or a genuine 200
    response) into the one `ExtractionResult` shape `_upsert_extraction`
    writes. Never raises — a classified failure IS a normal return value,
    because the worker itself must never raise (design D129: the terminal
    state must be deterministic and owned by this invocation, not by
    Lambda's disabled async retry)."""
    try:
        raw_response = textract.call_analyze_expense(bucket=bucket, key=key)
    except textract.TextractNonRetryableError as exc:
        return textract.ExtractionResult(
            status="failed",
            failure_reason=exc.failure_reason,
            attempt_count=1,
        )
    except textract.TextractRetriesExhaustedError as exc:
        return textract.ExtractionResult(
            status="failed",
            failure_reason="provider_unavailable",
            attempt_count=exc.attempts,
        )
    return textract.map_response(raw_response)


def process(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    transaction_id: uuid.UUID,
    key: str,
) -> bool:
    """Returns `True` if this invocation processed the record (i.e. found
    and transitioned a `pending_ocr` draft), `False` for every safe no-op
    case: not found (design D130's race, or a forged/replayed/foreign
    event), or a concurrent invocation that already claimed it."""
    transaction = _lock_pending_draft(
        db, workspace_id=workspace_id, transaction_id=transaction_id
    )
    if transaction is None:
        time.sleep(_NOT_FOUND_RETRY_DELAY_SECONDS)
        transaction = _lock_pending_draft(
            db, workspace_id=workspace_id, transaction_id=transaction_id
        )
    if transaction is None:
        return False

    settings = get_settings()
    result = _run_textract(bucket=settings.s3_receipts_bucket, key=key)

    _upsert_extraction(db, transaction_id=transaction.id, result=result)

    content_type = storage.object_content_type(key=key)
    if content_type is not None:
        transaction.photo_content_type = content_type
        transaction.photo_uploaded_at = datetime.datetime.now(datetime.UTC)

    new_status = (
        OcrStatus.EXTRACTED
        if result.status == "succeeded"
        else OcrStatus.EXTRACTION_FAILED
    )
    update_result = db.execute(
        sa.update(Transaction)
        .where(Transaction.id == transaction.id)
        .where(Transaction.workspace_id == workspace_id)
        .where(Transaction.ocr_status == OcrStatus.PENDING_OCR)
        .values(ocr_status=new_status, updated_at=datetime.datetime.now(datetime.UTC))
    )
    if update_result.rowcount == 0:
        # Someone else (another concurrent invocation) already moved this
        # row past `pending_ocr` between the lock above and this UPDATE.
        # The extraction upsert already wrote is harmless (design D127's
        # own upsert semantics), and the transition itself is a no-op —
        # design D116's idempotency guarantee.
        return False

    transaction.ocr_status = new_status
    db.commit()
    return True
