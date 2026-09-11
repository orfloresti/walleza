"""Business logic for the `recurring-transactions` capability (design
D45-D56). Every read/write here is built ONLY on top of
`app.recurring.queries.visible_recurring` (design D14's second structural
layer: a scopeless recurrence query is unwritable) — this module never
resolves membership itself and never builds a competing query path,
mirroring `app.transactions.service`/`app.templates.service` exactly.

This PR is CRUD-only (design's "Occurrence Generation Core" is a later
PR): `next_date` is initialized from `starts_on` at creation and is never
again written by anything in this module — `occurrence_index` and
`last_reminded_for_date` likewise stay untouched here, reserved for a
later PR's `app.recurring.generation`/reminder pass.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import UTC
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope
from app.recurring import schemas
from app.recurring.models import RecurringTransaction, RecurringTransactionSplit
from app.recurring.queries import visible_recurring


class RecurringNotFoundError(Exception):
    """Raised whenever a target recurrence id falls outside
    `visible_recurring` for the caller's scope. Design D18's 404
    convention (mirrors `TransactionNotFoundError`/`TemplateNotFoundError`
    exactly): a 403 would confirm the row exists at all."""


class RecurringValidationError(Exception):
    """Raised when `account_id` does not resolve inside the caller's own
    `visible_accounts(scope)`, or when `ends_on` precedes `starts_on`.
    Mapped to 422 by the router — never 404, mirrors
    `TransactionValidationError` exactly."""


class RecurringSplitValidationError(Exception):
    """Raised by `replace_recurring_splits` when a split line's
    `category_id` does not resolve inside the caller's own workspace, a
    `category_id` is repeated within the same request, or the split
    amounts do not sum EXACTLY to the recurrence's own amount. Mapped to
    422 by the router. Mirrors `TransactionSplitValidationError` exactly."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _validate_account_reference(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID
) -> None:
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise RecurringValidationError("account not found")


def _validate_ends_on(*, starts_on: datetime.date, ends_on: datetime.date | None) -> None:
    """Spec: "ends_on Must Not Precede the Start Date". Service-layer half
    of a two-layer guard — the DB CHECK
    `ck_recurring_transaction_ends_on_after_starts_on` is the backstop
    (mirrors design D42's two-layer pattern for transfers)."""
    if ends_on is not None and ends_on < starts_on:
        raise RecurringValidationError("ends_on must not precede the recurrence's start date")


def list_recurring(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID | None = None,
    is_subscription: bool | None = None,
) -> list[RecurringTransaction]:
    query = visible_recurring(
        scope, account_id=account_id, is_subscription=is_subscription
    ).order_by(RecurringTransaction.next_date, RecurringTransaction.created_at)
    return list(db.execute(query).scalars())


def get_recurring(
    db: Session, *, scope: WorkspaceScope, recurring_id: uuid.UUID
) -> RecurringTransaction:
    recurring = db.execute(
        visible_recurring(scope).where(RecurringTransaction.id == recurring_id)
    ).scalar_one_or_none()
    if recurring is None:
        raise RecurringNotFoundError("recurring transaction not found")
    return recurring


def create_recurring(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID,
    type: str,
    amount: Decimal,
    notes: str | None,
    is_refund: bool,
    is_subscription: bool,
    repeat_every: int,
    period: str,
    starts_on: datetime.date,
    ends_on: datetime.date | None,
    reminder_days_before: int | None,
    reminder_locale: str,
    created_by_user_id: uuid.UUID,
    splits: list[schemas.RecurringSplitIn] | None = None,
) -> RecurringTransaction:
    _validate_account_reference(db, scope=scope, account_id=account_id)
    _validate_ends_on(starts_on=starts_on, ends_on=ends_on)

    now = _now()
    recurring = RecurringTransaction(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        account_id=account_id,
        type=type,
        amount=amount,
        notes=notes,
        is_refund=is_refund,
        is_subscription=is_subscription,
        repeat_every=repeat_every,
        period=period,
        starts_on=starts_on,
        occurrence_index=0,
        # Spec: "next_date initialized to the start date" — the ONLY place
        # this column is ever set from anything but a later PR's
        # generation pass.
        next_date=starts_on,
        ends_on=ends_on,
        reminder_days_before=reminder_days_before,
        last_reminded_for_date=None,
        reminder_locale=reminder_locale,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(recurring)
    replace_recurring_splits(db, scope=scope, recurring=recurring, lines=splits or [])
    return recurring


def update_recurring(
    db: Session,
    *,
    scope: WorkspaceScope,
    recurring_id: uuid.UUID,
    changes: dict[str, object],
    splits: list[schemas.RecurringSplitIn] | None = None,
    splits_provided: bool = False,
) -> RecurringTransaction:
    """`changes` never contains `next_date`/`occurrence_index`/
    `last_reminded_for_date`/`starts_on` — those keys simply do not exist
    on `RecurringUpdateIn` (spec: "next_date Is Server-Managed"), so this
    function structurally cannot alter them regardless of what a caller
    sends."""
    recurring = get_recurring(db, scope=scope, recurring_id=recurring_id)

    if "account_id" in changes and changes["account_id"] is not None:
        _validate_account_reference(
            db, scope=scope, account_id=changes["account_id"]  # type: ignore[arg-type]
        )

    if "ends_on" in changes:
        _validate_ends_on(starts_on=recurring.starts_on, ends_on=changes["ends_on"])  # type: ignore[arg-type]

    if splits_provided:
        replace_recurring_splits(db, scope=scope, recurring=recurring, lines=splits or [])
    elif "amount" in changes:
        existing = list_recurring_splits(db, recurring_id=recurring.id)
        if existing:
            new_amount = changes["amount"]
            total = sum((line.amount for line in existing), start=Decimal(0))
            if total != new_amount:
                raise RecurringSplitValidationError(
                    f"existing splits ({total}) no longer sum to the updated "
                    f"recurrence amount ({new_amount}); update splits too"
                )

    next_date_before = recurring.next_date
    for field, value in changes.items():
        setattr(recurring, field, value)
    recurring.updated_at = _now()
    db.flush()
    # Structural assertion, not a re-derivation: nothing above ever touches
    # `next_date` (spec: "A client update to other fields ... MUST NOT
    # reset or otherwise alter next_date").
    assert recurring.next_date == next_date_before
    return recurring


def delete_recurring(db: Session, *, scope: WorkspaceScope, recurring_id: uuid.UUID) -> None:
    recurring = get_recurring(db, scope=scope, recurring_id=recurring_id)
    db.delete(recurring)
    db.flush()


def list_recurring_splits(
    db: Session, *, recurring_id: uuid.UUID
) -> list[RecurringTransactionSplit]:
    return list(
        db.execute(
            sa.select(RecurringTransactionSplit)
            .where(RecurringTransactionSplit.recurring_transaction_id == recurring_id)
            .order_by(RecurringTransactionSplit.id)
        ).scalars()
    )


def replace_recurring_splits(
    db: Session,
    *,
    scope: WorkspaceScope,
    recurring: RecurringTransaction,
    lines: list[schemas.RecurringSplitIn],
) -> None:
    """The ONLY function that ever writes a `recurring_transaction_split`
    row. Mirrors `app.transactions.service.replace_splits` exactly."""
    if lines:
        category_ids = {line.category_id for line in lines}
        if len(category_ids) != len(lines):
            raise RecurringSplitValidationError(
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
            raise RecurringSplitValidationError(
                "one or more split categories are not visible in this workspace"
            )

        total = sum((line.amount for line in lines), start=Decimal(0))
        if total != recurring.amount:
            raise RecurringSplitValidationError(
                f"split amounts must sum exactly to the recurrence amount "
                f"(got {total}, expected {recurring.amount})"
            )

    db.execute(
        sa.delete(RecurringTransactionSplit).where(
            RecurringTransactionSplit.recurring_transaction_id == recurring.id
        )
    )
    for line in lines:
        db.add(
            RecurringTransactionSplit(
                id=uuid.uuid4(),
                recurring_transaction_id=recurring.id,
                category_id=line.category_id,
                amount=line.amount,
            )
        )
    db.flush()
