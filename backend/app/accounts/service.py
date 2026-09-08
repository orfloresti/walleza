"""Business logic for the `account-management`/`account-visibility`
capabilities: CRUD, archive, and the `/api/workspace/summary` aggregate
(design D16). Every read/write here is built ONLY on top of
`app.accounts.queries.visible_accounts` (design D14's second structural
layer: a scopeless account query is unwritable) — this module never
resolves membership itself and never builds a competing query path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope


class AccountNotFoundError(Exception):
    """Raised whenever a target account id falls outside
    `visible_accounts` for the caller's scope — whether the row belongs to
    a different workspace entirely, or is another member's personal
    account within the SAME workspace. Design D18 maps both cases to an
    identical 404: a 403 would confirm the row exists at all, which is
    exactly the leak D18 forbids."""


def _now() -> datetime:
    return datetime.now(UTC)


def list_accounts(db: Session, *, scope: WorkspaceScope, archived: bool) -> list[Account]:
    query = visible_accounts(scope, archived=archived).order_by(Account.created_at)
    return list(db.execute(query).scalars())


def get_account(db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID) -> Account:
    """Fetch-by-id is intentionally NOT archived-filtered (`visible_accounts`
    called with no `archived=` kwarg) — a direct lookup by id is not a
    "listing"; only `list_accounts`'s default and `compute_summary` apply
    the `archived=False` filter (decision 6 / design D16)."""
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError("account not found")
    return account


def create_account(
    db: Session,
    *,
    scope: WorkspaceScope,
    name: str,
    currency: str,
    exchange_rate: Decimal,
    initial_funds: Decimal,
    is_personal: bool,
) -> Account:
    now = _now()
    account = Account(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        owner_user_id=scope.user_id if is_personal else None,
        name=name,
        currency=currency,
        exchange_rate=exchange_rate,
        initial_funds=initial_funds,
        is_personal=is_personal,
        archived=False,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.flush()
    return account


def update_account(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID,
    changes: dict[str, object],
) -> Account:
    """`changes` is the caller's already-`exclude_unset=True`-filtered
    patch body — only fields explicitly present in the request are
    applied. Fetching through `get_account` (i.e. through
    `visible_accounts`) means a PATCH aimed at another member's personal
    account 404s before any write is attempted, structurally, with no
    separate ownership check needed here."""
    account = get_account(db, scope=scope, account_id=account_id)
    for field, value in changes.items():
        setattr(account, field, value)
    account.updated_at = _now()
    db.flush()
    return account


@dataclass(frozen=True)
class CurrencyTotal:
    currency: str
    total: Decimal


@dataclass(frozen=True)
class AccountSummary:
    by_currency: list[CurrencyTotal]
    grand_total: Decimal


def compute_summary(db: Session, *, scope: WorkspaceScope) -> AccountSummary:
    """Design D16: a SQL aggregate over the EXACT SAME `Select`
    `list_accounts`'s default call (`archived=False`) uses — both derive
    from the identical `visible_accounts(scope, archived=False)` call, so
    a total structurally cannot count a row the default account list
    would hide. Per-currency `SUM(initial_funds)` plus a converted grand
    total `SUM(initial_funds * exchange_rate)` — Phase 1 has no
    transactions yet, so "balance" is exactly `initial_funds` (design
    D16's own note: "Phase 2 extends one expression in one file")."""
    base = visible_accounts(scope, archived=False).subquery()

    by_currency_rows = db.execute(
        sa.select(base.c.currency, sa.func.sum(base.c.initial_funds).label("total"))
        .group_by(base.c.currency)
        .order_by(base.c.currency)
    ).all()
    by_currency = [CurrencyTotal(currency=row.currency, total=row.total) for row in by_currency_rows]

    grand_total = db.execute(
        sa.select(sa.func.coalesce(sa.func.sum(base.c.initial_funds * base.c.exchange_rate), 0))
    ).scalar_one()

    return AccountSummary(by_currency=by_currency, grand_total=Decimal(grand_total))
