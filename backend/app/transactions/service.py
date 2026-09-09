"""Business logic for the `transaction-management`/`transaction-visibility`/
`transaction-splits`/`transaction-attachments` capabilities (design D22,
D24, D30). Every read/write here is built ONLY on top of
`app.transactions.queries.visible_transactions` (design D14's second
structural layer: a scopeless transaction query is unwritable) — this
module never resolves membership itself and never builds a competing
query path (mirrors `app.accounts.service`/`app.categories.service`
exactly).

PR3b added split allocation write logic: `replace_splits` is the ONLY
function that ever writes a `transaction_category_split` row (design
D22 — application-layer-only sum invariant, one function, whole-set
replacement, never a partial edit, never a DB trigger). Account balance
(`app.accounts.service.compute_summary`) is untouched here — design D34
explicitly defers netting transaction amounts into it to Phase 6.

PR5 adds the photo upload-url/confirm/download flow (design D24). Every
one of `request_photo_upload_url`/`confirm_photo_upload`/
`request_photo_download_url` calls `get_transaction` (i.e.
`visible_transactions`) FIRST, before touching `app.storage` at all —
authorization strictly precedes issuance, the single most important
security property design D24 names. `app.storage` is imported as a
MODULE (`from app import storage`, never `from app.storage import ...`)
so a test can monkeypatch `storage.presigned_upload`/etc. as a module
attribute and have every call site here observe the replacement.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import UTC
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import storage
from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.categories.models import Category
from app.categories.queries import visible_categories
from app.config import get_settings
from app.deps import WorkspaceScope
from app.transactions import schemas
from app.transactions.models import Transaction, TransactionCategorySplit
from app.transactions.queries import visible_transactions


class TransactionNotFoundError(Exception):
    """Raised whenever a target transaction id falls outside
    `visible_transactions` for the caller's scope — whether the row
    belongs to a different workspace entirely, or sits on another
    member's personal account within the SAME workspace. Design D18 maps
    both cases to an identical 404: a 403 would confirm the row exists at
    all, which is exactly the leak D18 forbids."""


class TransactionValidationError(Exception):
    """Raised when `account_id` does not resolve inside the caller's own
    `visible_accounts(scope)` — a different workspace's account, or
    another member's personal account in the SAME workspace. Mapped to
    422 by the router — never 404, because `account_id` is a request BODY
    field, not a resource being fetched by id (mirrors
    `app.categories.service.CategoryValidationError`'s cross-workspace
    `parent_id` handling exactly: reject as if the reference did not
    exist, never silently accept a foreign-scope id)."""


class TransactionPhotoNotUploadedError(Exception):
    """Raised by `confirm_photo_upload` when `app.storage.object_exists`
    reports no object at the transaction's derived key — the caller
    requested an upload URL but never actually completed the upload to
    S3, or uploaded to a different key entirely. Mapped to 409 by the
    router; `photo_content_type`/`photo_uploaded_at` are left untouched
    (both stay NULL, or keep their previous value on a re-confirm
    attempt), so the DB's `(photo_content_type IS NULL) =
    (photo_uploaded_at IS NULL)` CHECK constraint always still holds."""


class TransactionSplitValidationError(Exception):
    """Raised by `replace_splits` (design D22) when either a split line's
    `category_id` does not resolve inside the caller's own workspace
    (`app.categories.queries.visible_categories`), a `category_id` is
    repeated within the same request, or the split amounts do not sum
    EXACTLY (Decimal, never float-tolerant) to the transaction's own
    amount. Also raised by `update_transaction` when `amount` changes but
    `splits` is left untouched and the existing splits no longer sum to
    the new amount. Mapped to 422 by the router. Validation always runs
    BEFORE any existing split row is deleted or any new split row is
    inserted — a rejected request leaves every existing split row
    byte-for-byte untouched (no partial write)."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _validate_account_reference(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID
) -> None:
    """Design's "Account FK Must Belong to the Requester's Own Workspace"
    requirement: `account_id` must resolve inside
    `visible_accounts(scope)` — i.e. it must be an account in the
    caller's own workspace that is either shared or the caller's own
    personal account. An id from another workspace, or another member's
    personal account in the same workspace, is rejected identically."""
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise TransactionValidationError("account not found")


def list_transactions(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    type: str | None = None,
) -> list[Transaction]:
    query = visible_transactions(
        scope,
        account_id=account_id,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
        type=type,
    ).order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
    return list(db.execute(query).scalars())


def get_transaction(
    db: Session, *, scope: WorkspaceScope, transaction_id: uuid.UUID
) -> Transaction:
    transaction = db.execute(
        visible_transactions(scope).where(Transaction.id == transaction_id)
    ).scalar_one_or_none()
    if transaction is None:
        raise TransactionNotFoundError("transaction not found")
    return transaction


def create_transaction(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID,
    type: str,
    amount: Decimal,
    occurred_on: datetime.date,
    notes: str | None,
    is_refund: bool,
    checked: bool,
    created_by_user_id: uuid.UUID | None = None,
    splits: list[schemas.SplitIn] | None = None,
) -> Transaction:
    _validate_account_reference(db, scope=scope, account_id=account_id)

    now = _now()
    transaction = Transaction(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        account_id=account_id,
        type=type,
        amount=amount,
        occurred_on=occurred_on,
        notes=notes,
        is_refund=is_refund,
        checked=checked,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(transaction)
    # `replace_splits` is the ONLY place a split row is ever written
    # (design D22). It validates BEFORE issuing its own `db.flush()`, so a
    # rejected request never flushes the pending `transaction` insert
    # either — nothing reaches the database (no partial write).
    replace_splits(db, scope=scope, transaction=transaction, lines=splits or [])
    return transaction


def update_transaction(
    db: Session,
    *,
    scope: WorkspaceScope,
    transaction_id: uuid.UUID,
    changes: dict[str, object],
    splits: list[schemas.SplitIn] | None = None,
    splits_provided: bool = False,
) -> Transaction:
    """`changes` is the caller's already-`exclude_unset=True`-filtered
    patch body (with `splits` already popped out by the router, since it
    is not a plain `Transaction` column) — only fields explicitly present
    in the request are applied. Fetching through `get_transaction` (i.e.
    through `visible_transactions`) means a PATCH aimed at another
    member's personal-account transaction 404s before any write is
    attempted, structurally, with no separate ownership check needed
    here.

    `splits_provided=True` means the request body named `splits` at all
    (including an explicit empty list) — that always replaces the whole
    split set via `replace_splits` (design D22, never additive). When
    `splits_provided=False` but `amount` is being changed, the EXISTING
    splits (if any) must still sum to the NEW amount, or the update is
    rejected (spec: "Updating amount without updating splits is
    rejected") — this is the sum invariant applied to a set of lines the
    caller never touched, so no row is deleted/inserted, only checked."""
    transaction = get_transaction(db, scope=scope, transaction_id=transaction_id)

    if "account_id" in changes and changes["account_id"] is not None:
        _validate_account_reference(
            db, scope=scope, account_id=changes["account_id"]  # type: ignore[arg-type]
        )

    if splits_provided:
        replace_splits(db, scope=scope, transaction=transaction, lines=splits or [])
    elif "amount" in changes:
        existing = list_splits(db, transaction_id=transaction.id)
        if existing:
            new_amount = changes["amount"]
            total = sum((line.amount for line in existing), start=Decimal(0))
            if total != new_amount:
                raise TransactionSplitValidationError(
                    f"existing splits ({total}) no longer sum to the updated "
                    f"transaction amount ({new_amount}); update splits too"
                )

    for field, value in changes.items():
        setattr(transaction, field, value)
    transaction.updated_at = _now()
    db.flush()
    return transaction


def delete_transaction(
    db: Session, *, scope: WorkspaceScope, transaction_id: uuid.UUID
) -> None:
    """Deletes the transaction row only. Design D27's best-effort S3
    cleanup (`storage.delete_object`) deliberately does NOT happen here —
    it must run strictly AFTER the caller's own `db.commit()` has
    actually succeeded (DB-first-then-S3 ordering), and this function has
    no way to know whether its caller's session will actually commit or
    roll back. `app.transactions.router.delete_transaction` is the one
    place that owns both the commit and the subsequent best-effort S3
    call."""
    transaction = get_transaction(db, scope=scope, transaction_id=transaction_id)
    db.delete(transaction)
    db.flush()


def request_photo_upload_url(
    db: Session, *, scope: WorkspaceScope, transaction_id: uuid.UUID, content_type: str
) -> dict[str, object]:
    """Design D24 step ②: `get_transaction` (i.e. `visible_transactions`)
    resolves BEFORE `storage.presigned_upload` is ever called — a
    transaction outside the caller's visibility 404s here with NO
    presigned URL generated at all, and with `app.storage` never invoked.
    This ordering is the single most important security property in the
    whole `transaction-attachments` capability (spec's "Presigned URL
    Authorization Precedes Issuance" requirement)."""
    transaction = get_transaction(db, scope=scope, transaction_id=transaction_id)
    settings = get_settings()
    key = storage.receipt_object_key(scope.workspace_id, transaction.id)
    payload = storage.presigned_upload(key=key, content_type=content_type)
    return {
        "url": payload["url"],
        "fields": payload["fields"],
        "expires_at": _now() + datetime.timedelta(seconds=settings.presigned_url_ttl_seconds),
        "max_bytes": settings.receipt_max_bytes,
        "content_type": content_type,
    }


def confirm_photo_upload(
    db: Session, *, scope: WorkspaceScope, transaction_id: uuid.UUID, content_type: str
) -> Transaction:
    """Design D24 step ④: re-authorizes via `get_transaction`, then
    `storage.object_exists` proves the object actually landed BEFORE
    `photo_content_type`/`photo_uploaded_at` are ever set — a confirm for
    an object nobody actually uploaded raises
    `TransactionPhotoNotUploadedError` (409) with the row left untouched."""
    transaction = get_transaction(db, scope=scope, transaction_id=transaction_id)
    key = storage.receipt_object_key(scope.workspace_id, transaction.id)
    if not storage.object_exists(key=key):
        raise TransactionPhotoNotUploadedError(
            "no object has been uploaded for this transaction yet"
        )
    transaction.photo_content_type = content_type
    transaction.photo_uploaded_at = _now()
    transaction.updated_at = _now()
    db.flush()
    return transaction


def request_photo_download_url(
    db: Session, *, scope: WorkspaceScope, transaction_id: uuid.UUID
) -> dict[str, object]:
    """Design D24 step ⑤/D26: re-authorizes via `get_transaction` BEFORE
    any presigned GET is generated — same authorization-before-issuance
    discipline as the upload side. A visible transaction with no photo
    yet (`photo_uploaded_at IS NULL`) raises the SAME
    `TransactionNotFoundError` (404) an invisible transaction would —
    spec's "same status, no oracle" requirement: a caller must not be
    able to distinguish "hidden" from "visible but no photo" by status
    code alone."""
    transaction = get_transaction(db, scope=scope, transaction_id=transaction_id)
    if transaction.photo_uploaded_at is None or transaction.photo_content_type is None:
        raise TransactionNotFoundError("no photo attached to this transaction")
    settings = get_settings()
    key = storage.receipt_object_key(scope.workspace_id, transaction.id)
    url = storage.presigned_download(key=key, content_type=transaction.photo_content_type)
    return {
        "url": url,
        "expires_at": _now() + datetime.timedelta(seconds=settings.presigned_url_ttl_seconds),
    }


def list_splits(
    db: Session, *, transaction_id: uuid.UUID
) -> list[TransactionCategorySplit]:
    """Read path for a transaction's current split lines, ordered for
    stable output. A plain lookup by `transaction_id` — it does not
    re-check visibility, because every caller already reached this
    `transaction_id` through `get_transaction`/`visible_transactions`
    (design D30's own chokepoint: a split line is only ever reachable by
    first resolving its parent transaction through scope, spec's "a split
    line does not leak account ownership" scenario)."""
    return list(
        db.execute(
            sa.select(TransactionCategorySplit)
            .where(TransactionCategorySplit.transaction_id == transaction_id)
            .order_by(TransactionCategorySplit.id)
        ).scalars()
    )


def replace_splits(
    db: Session,
    *,
    scope: WorkspaceScope,
    transaction: Transaction,
    lines: list[schemas.SplitIn],
) -> None:
    """Design D22: the ONLY function that ever writes a
    `transaction_category_split` row. Splits are never partially edited —
    every create/update that touches them goes through this one
    whole-set replacement, wrapped in the caller's own (uncommitted)
    session transaction. Validation (category visibility + exact Decimal
    sum) always runs BEFORE any existing split row is deleted or any new
    split row is inserted, so a rejected request leaves every existing
    split row byte-for-byte untouched — the router never calls
    `db.commit()` on the exception path, so even the DELETE statement
    below never actually persists when validation fails earlier."""
    if lines:
        category_ids = {line.category_id for line in lines}
        if len(category_ids) != len(lines):
            raise TransactionSplitValidationError(
                "a category cannot appear more than once in the same split set"
            )

        visible_ids = {
            row.id
            for row in db.execute(
                visible_categories(scope).where(Category.id.in_(category_ids))
            ).scalars()
        }
        missing = category_ids - visible_ids
        if missing:
            raise TransactionSplitValidationError(
                "one or more split categories are not visible in this workspace"
            )

        total = sum((line.amount for line in lines), start=Decimal(0))
        if total != transaction.amount:
            raise TransactionSplitValidationError(
                f"split amounts must sum exactly to the transaction amount "
                f"(got {total}, expected {transaction.amount})"
            )

    db.execute(
        sa.delete(TransactionCategorySplit).where(
            TransactionCategorySplit.transaction_id == transaction.id
        )
    )
    for line in lines:
        db.add(
            TransactionCategorySplit(
                id=uuid.uuid4(),
                transaction_id=transaction.id,
                category_id=line.category_id,
                amount=line.amount,
            )
        )
    db.flush()
