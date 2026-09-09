"""Business logic for the `transfer-management` capability (design
D36-D42). Every read/write here is built ONLY on top of
`app.transfers.queries.visible_transfers` (design D14's second structural
layer: a scopeless transfer query is unwritable) — this module never
resolves membership itself and never builds a competing query path,
mirroring `app.transactions.service` exactly.

There is deliberately no `update_transfer` (design D43/proposal T6): a
transfer's fields, once created, can only be corrected by deleting the
transfer and creating a new one. No route, no service function, no
schema exists for it anywhere in this module or `app.transfers.router` —
the absence is structural, not merely undocumented.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import UTC
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.transfers.models import Transfer
from app.transfers.queries import visible_transfers

CENTS = Decimal("0.01")


class TransferNotFoundError(Exception):
    """Raised whenever a target transfer id falls outside
    `visible_transfers` for the caller's scope — whether the row belongs
    to a different workspace entirely, or resolves on only ONE side for
    the caller (design D38's dual-INNER-JOIN structurally makes a
    one-sided-visible transfer invisible on every verb: list, GET-by-id,
    DELETE). Mapped to 404 by the router — design D41: a whole resource
    addressed by id in the URL, outside `visible_transfers`, mirrors
    `get_transaction`'s `TransactionNotFoundError` precedent exactly."""


class TransferValidationError(Exception):
    """Raised when `from_account_id`/`to_account_id` does not resolve
    inside the caller's own `visible_accounts(scope)` (either side,
    independently — passing on one side never excuses the other), when
    `from_account_id == to_account_id`, or when the derived `to_amount`
    quantizes to `<= 0`. Mapped to 422 by the router — design D41: an
    invalid reference or value INSIDE a request body, never 404, mirrors
    `TransactionValidationError`'s cross-workspace `account_id` handling
    exactly."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _validate_account_reference(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID
) -> Account:
    """Mirrors `app.transactions.service._validate_account_reference`
    exactly (design's "Both Accounts Must Resolve" requirement, proposal
    T3): the account must resolve inside `visible_accounts(scope)` — the
    caller's own workspace, and either shared or the caller's own
    personal account. An id from another workspace, or another member's
    personal account in the same workspace, is rejected identically.
    Returns the resolved `Account` row so `_derive_to_amount` can read
    its `exchange_rate` without a second query."""
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise TransferValidationError("account not found")
    return account


def _derive_to_amount(
    from_amount: Decimal, from_account: Account, to_account: Account
) -> Decimal:
    """Design D40: multiply BEFORE divide — the multiplication is exact
    (both operands are exact Decimals), so exactly ONE inexact operation
    (the division) occurs, immediately before an explicit `quantize`.
    Ratio-first would truncate the rate ratio and then AMPLIFY that
    truncation by `from_amount`.

    `ROUND_HALF_UP` matches Postgres `numeric`'s own half-away-from-zero
    rounding, so this explicit quantize and any DB-side coercion agree.
    The explicit quantize itself matters as much as the rounding mode:
    without it, a high-precision `Decimal` would reach the
    `numeric(18,2)` column and Postgres would silently round on insert —
    this makes the rounding rule visible and tested instead of an
    invisible DB-side default.

    A result that rounds to `<= 0` (tiny `from_amount`, large
    `to_account.exchange_rate`) is a real reachable case that would
    otherwise hit `ck_transfer_to_amount_positive` as an
    `IntegrityError`/500 — caught here and returned as a clean 422."""
    raw = from_amount * from_account.exchange_rate / to_account.exchange_rate
    to_amount = raw.quantize(CENTS, rounding=ROUND_HALF_UP)
    if to_amount <= 0:
        raise TransferValidationError(
            f"the converted destination amount rounds to {to_amount}; "
            f"increase the amount or check the accounts' exchange rates"
        )
    return to_amount


def list_transfers(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> list[Transfer]:
    query = visible_transfers(
        scope, account_id=account_id, date_from=date_from, date_to=date_to
    ).order_by(Transfer.occurred_on.desc(), Transfer.created_at.desc())
    return list(db.execute(query).scalars())


def get_transfer(db: Session, *, scope: WorkspaceScope, transfer_id: uuid.UUID) -> Transfer:
    transfer = db.execute(
        visible_transfers(scope).where(Transfer.id == transfer_id)
    ).scalar_one_or_none()
    if transfer is None:
        raise TransferNotFoundError("transfer not found")
    return transfer


def create_transfer(
    db: Session,
    *,
    scope: WorkspaceScope,
    from_account_id: uuid.UUID,
    to_account_id: uuid.UUID,
    from_amount: Decimal,
    occurred_on: datetime.date,
    notes: str | None,
    created_by_user_id: uuid.UUID | None = None,
) -> Transfer:
    # Design's Data Flow ①②: both sides checked independently — passing
    # on one side never excuses the other.
    from_account = _validate_account_reference(db, scope=scope, account_id=from_account_id)
    to_account = _validate_account_reference(db, scope=scope, account_id=to_account_id)

    # Design D42, service layer of the two-layer guard: a clean 422
    # instead of an unhandled IntegrityError/500 from the DB CHECK below.
    if from_account_id == to_account_id:
        raise TransferValidationError("from_account_id and to_account_id must differ")

    to_amount = _derive_to_amount(from_amount, from_account, to_account)

    now = _now()
    transfer = Transfer(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        from_amount=from_amount,
        to_amount=to_amount,
        occurred_on=occurred_on,
        notes=notes,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(transfer)
    db.flush()
    return transfer


def delete_transfer(db: Session, *, scope: WorkspaceScope, transfer_id: uuid.UUID) -> None:
    """Deletes exactly the one `app.transfer` row — no paired row, no
    cascading transaction, no orphaned reference (design T1/T6: a
    transfer is one row, never a linked pair)."""
    transfer = get_transfer(db, scope=scope, transfer_id=transfer_id)
    db.delete(transfer)
    db.flush()
