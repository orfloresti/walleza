"""Abandoned-draft TTL sweep (design D124) — Phase 9 Unit 6.

Runs as Pass C in `app.scheduler`'s existing daily Lambda invocation
(design D45's precedent: no new infrastructure, no new EventBridge rule,
no new IAM role for the Lambda itself — only an additional `s3:DeleteObject`
grant on the scheduler's existing execution role, `infra/scheduler.tf`).

Like `app.recurring.generation.run`/`run_reminders`, this scan is
deliberately CROSS-WORKSPACE and scopeless (design's Data Flow, mirroring
`generation.run`'s own docstring) — it is a background job with no
authenticated caller, not a member-scoped request, so it queries
`app.transaction` directly rather than through `WorkspaceScope`-gated
`visible_transactions`/`ocr_draft_transactions` (both of which require a
scope this pass does not have and should not fabricate).

Deletion targets: any row whose `ocr_status` is set and is NOT
`'confirmed'` (i.e. `pending_ocr`, `extracted`, or `extraction_failed` —
enumerated explicitly rather than via `!= 'confirmed'` so a future new
`OcrStatus` member does not silently become sweepable without a decision)
AND `created_at` older than `settings.ocr_draft_ttl_days` (default 7,
design D124). A `confirmed` transaction is a real transaction now and is
never touched, regardless of age; a NULL `ocr_status` row (the vast
majority of the table) never matches at all.

S3 cleanup decision (recorded here, apply-progress obs — not addressed by
name in design D124's own alternatives list, which frames the choice as
"indefinite retention" vs "the sweep exists"): the associated receipt
photo IS deleted, best-effort, same ordering discipline as `storage.
delete_object`'s existing caller in
`app.transactions.router.delete_transaction` (design D27) — DB delete
commits FIRST, S3 delete second, and any S3-side error is swallowed and
logged, never rolled back into the DB transaction and never raised to the
caller. Rationale: D124's own stated risk is "an invisible immortal row
holding receipt data" — the row is the half that is dangerous (unbounded,
invisible, holds real financial+PII content indefinitely); the S3 object
is comparatively inert (private bucket, non-guessable key, no cross-
reference once its owning row is gone) and its ONLY cost is storage
dollars, not correctness or privacy exposure beyond what already existed
for a confirmed transaction's photo. But leaving it forever after its
owning row is deleted is a pure, avoidable ongoing storage cost with zero
offsetting benefit (no code path can ever reach that key again once the
row is gone — `receipt_object_key` is a pure function of
`(workspace_id, transaction_id)`, and this transaction_id can never be
reused), so cleaning it up is strictly better with no additional risk.
`storage.delete_object` already exists and is reused verbatim rather than
reinvented.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import storage
from app.config import get_settings
from app.transactions.models import OcrStatus, Transaction

logger = logging.getLogger(__name__)

# Design D124: explicit enumeration of the sweepable (non-terminal-success)
# statuses, deliberately excluding `CONFIRMED` — never widen this via
# `!= CONFIRMED`, so a future new `OcrStatus` member requires a conscious
# decision about whether it belongs in the sweep.
_SWEEPABLE_STATUSES = (
    OcrStatus.PENDING_OCR,
    OcrStatus.EXTRACTED,
    OcrStatus.EXTRACTION_FAILED,
)


def sweep_abandoned_drafts(db: Session, *, now: datetime) -> dict[str, int]:
    """Pass C (design D124). `now` is a PARAMETER, never read from the
    clock here — mirroring `generation.run`/`run_reminders`'s own
    `today` parameter (design D45's threat case 2 discipline: tests stay
    deterministic, and `app.scheduler.handler` is the only place
    `datetime.now()` appears).

    Cross-workspace, scopeless scan (see module docstring). Each deleted
    row's associated S3 receipt object is removed best-effort, AFTER the
    DB delete has already committed — see module docstring for the
    ordering rationale (mirrors design D27 / `storage.delete_object`'s
    existing caller).

    Returns `{"deleted": n}` for CloudWatch log inspection, matching
    `generation.run`'s summary-dict convention."""
    settings = get_settings()
    cutoff = now - timedelta(days=settings.ocr_draft_ttl_days)

    stale = db.execute(
        sa.select(Transaction.id, Transaction.workspace_id)
        .where(Transaction.ocr_status.in_(_SWEEPABLE_STATUSES))
        .where(Transaction.created_at < cutoff)
    ).all()

    if not stale:
        return {"deleted": 0}

    ids = [row.id for row in stale]
    # One commit for the whole pass (design D124's "own commit boundary" —
    # never shared with Pass A/B's transactions), mirroring `scheduler.py`'s
    # existing per-pass, not per-row, boundary discipline. Re-filtering on
    # `ocr_status`/`created_at` in the DELETE itself (not just the earlier
    # SELECT) guards against a row being confirmed between the scan and the
    # delete in this same transaction.
    db.execute(
        sa.delete(Transaction)
        .where(Transaction.id.in_(ids))
        .where(Transaction.ocr_status.in_(_SWEEPABLE_STATUSES))
        .where(Transaction.created_at < cutoff)
    )
    db.commit()

    for transaction_id, workspace_id in stale:
        _best_effort_delete_receipt(workspace_id=workspace_id, transaction_id=transaction_id)

    return {"deleted": len(stale)}


def _best_effort_delete_receipt(*, workspace_id: uuid.UUID, transaction_id: uuid.UUID) -> None:
    """Design D27's exact "best-effort, does not fail the caller"
    semantics, reused rather than reinvented: runs strictly AFTER the
    owning row's DB delete has already committed, and any `ClientError`
    (or other S3-side failure) is swallowed and logged — the DB delete is
    already durable and must never be retried, rolled back, or turned
    into a sweep failure because of an S3-side hiccup."""
    key = storage.receipt_object_key(workspace_id, transaction_id)
    try:
        storage.delete_object(key=key)
    except Exception:
        logger.exception(
            "sweep_abandoned_drafts: best-effort S3 delete failed for transaction %s",
            transaction_id,
        )
