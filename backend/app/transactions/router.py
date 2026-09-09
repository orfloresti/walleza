"""FastAPI routes for the `transaction-management`/`transaction-visibility`/
`transaction-splits`/`transaction-attachments` capabilities (design D14,
D18, D19, D22, D24, D27, D30). `APIRouter(dependencies=[Depends
(require_membership)])` — every route on this router inherits the
membership gate with no per-route opt-in required (design D14), mirroring
`app/accounts/router.py` and `app/categories/router.py` exactly.

PR3b wired the inline `splits` field into create/update (spec's
Interfaces/Contracts note: splits are modeled inline in the transaction
payload, never a separate sub-resource). PR5 adds the three photo
endpoints (upload-url/confirm/download, design D24) and, on
`delete_transaction`, a best-effort S3 cleanup call AFTER the DB commit
already succeeded (design D27) — an S3-side failure there is logged and
swallowed, never allowed to roll back or fail the already-successful 204.
"""

from __future__ import annotations

import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import storage
from app.db import get_db
from app.deps import WorkspaceScope, require_membership
from app.transactions import schemas, service
from app.transactions.models import Transaction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["transactions"], dependencies=[Depends(require_membership)])


def _to_out(db: Session, transaction: Transaction) -> schemas.TransactionOut:
    """Attaches the transaction's current split-line snapshot (design
    D22) to the response. A plain field-by-field construction rather than
    `TransactionOut.model_validate(transaction)` because `Transaction` has
    no ORM relationship to its splits (design's query-builder-only
    convention, mirroring `visible_transactions`'s own EXISTS-not-JOIN
    choice — no lazy-loaded relationship to accidentally reintroduce a
    cardinality hazard)."""
    splits = service.list_splits(db, transaction_id=transaction.id)
    return schemas.TransactionOut(
        id=transaction.id,
        workspace_id=transaction.workspace_id,
        account_id=transaction.account_id,
        type=transaction.type,
        amount=transaction.amount,
        occurred_on=transaction.occurred_on,
        notes=transaction.notes,
        is_refund=transaction.is_refund,
        checked=transaction.checked,
        photo_content_type=transaction.photo_content_type,
        photo_uploaded_at=transaction.photo_uploaded_at,
        created_by_user_id=transaction.created_by_user_id,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
        splits=[schemas.SplitOut.model_validate(s) for s in splits],
    )


@router.get("/api/transactions", response_model=list[schemas.TransactionOut])
def list_transactions(
    account_id: uuid.UUID | None = Query(default=None),
    category_id: uuid.UUID | None = Query(default=None),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    type: schemas.TransactionType | None = Query(default=None),
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.TransactionOut]:
    transactions = service.list_transactions(
        db,
        scope=scope,
        account_id=account_id,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        type=type,
    )
    return [_to_out(db, t) for t in transactions]


@router.post("/api/transactions", response_model=schemas.TransactionOut, status_code=201)
def create_transaction(
    body: schemas.TransactionCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TransactionOut:
    try:
        transaction = service.create_transaction(
            db,
            scope=scope,
            account_id=body.account_id,
            type=body.type,
            amount=body.amount,
            occurred_on=body.occurred_on,
            notes=body.notes,
            is_refund=body.is_refund,
            checked=body.checked,
            created_by_user_id=scope.user_id,
            splits=body.splits,
        )
    except service.TransactionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TransactionSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, transaction)


@router.get("/api/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def get_transaction(
    transaction_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TransactionOut:
    try:
        transaction = service.get_transaction(db, scope=scope, transaction_id=transaction_id)
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return _to_out(db, transaction)


@router.patch("/api/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def update_transaction(
    transaction_id: uuid.UUID,
    body: schemas.TransactionUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TransactionOut:
    raw = body.model_dump(exclude_unset=True)
    splits_provided = "splits" in raw
    raw.pop("splits", None)
    try:
        transaction = service.update_transaction(
            db,
            scope=scope,
            transaction_id=transaction_id,
            changes=raw,
            splits=body.splits,
            splits_provided=splits_provided,
        )
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    except service.TransactionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TransactionSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, transaction)


@router.delete("/api/transactions/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_transaction(db, scope=scope, transaction_id=transaction_id)
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    db.commit()

    # Design D27: DB-first-then-S3, best-effort, unconditional (no photo
    # existence check first — a `delete_object` on a key that was never
    # written is a normal S3 no-op, not an error). The row above is
    # ALREADY deleted and committed; an S3-side failure here must never
    # roll back that commit, retry, or turn this already-successful 204
    # into a failed response — it is only logged.
    key = storage.receipt_object_key(scope.workspace_id, transaction_id)
    try:
        storage.delete_object(key=key)
    except Exception:
        logger.warning(
            "best-effort S3 delete_object failed for transaction %s (key=%s); "
            "the transaction row is already deleted and this is not retried",
            transaction_id,
            key,
            exc_info=True,
        )


@router.post(
    "/api/transactions/{transaction_id}/photo/upload-url",
    response_model=schemas.PhotoUploadUrlOut,
    status_code=201,
)
def request_photo_upload_url(
    transaction_id: uuid.UUID,
    body: schemas.PhotoUploadUrlIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.PhotoUploadUrlOut:
    try:
        payload = service.request_photo_upload_url(
            db,
            scope=scope,
            transaction_id=transaction_id,
            content_type=body.content_type,
        )
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return schemas.PhotoUploadUrlOut(**payload)


@router.put(
    "/api/transactions/{transaction_id}/photo",
    response_model=schemas.PhotoConfirmOut,
)
def confirm_photo_upload(
    transaction_id: uuid.UUID,
    body: schemas.PhotoConfirmIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.PhotoConfirmOut:
    try:
        transaction = service.confirm_photo_upload(
            db,
            scope=scope,
            transaction_id=transaction_id,
            content_type=body.content_type,
        )
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    except service.TransactionPhotoNotUploadedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return schemas.PhotoConfirmOut(
        photo_content_type=transaction.photo_content_type,
        photo_uploaded_at=transaction.photo_uploaded_at,
    )


@router.get(
    "/api/transactions/{transaction_id}/photo",
    response_model=schemas.PhotoDownloadUrlOut,
)
def request_photo_download_url(
    transaction_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.PhotoDownloadUrlOut:
    try:
        payload = service.request_photo_download_url(
            db, scope=scope, transaction_id=transaction_id
        )
    except service.TransactionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transaction not found") from exc
    return schemas.PhotoDownloadUrlOut(**payload)
