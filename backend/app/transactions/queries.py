"""Scope-aware query builder for the `transaction-visibility` capability
(design D30). `visible_transactions` is the ONLY sanctioned way to build a
transaction-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.accounts.queries.visible_accounts` and
`app.categories.queries.visible_categories` (design D14's second
structural layer: a scopeless query is unwritable).

A transaction carries NO visibility state of its own (proposal decision
#6): it JOINs `visible_accounts(scope)` — called with no `archived`
kwarg, exactly per D30 — as a subquery, so D15's predicate keeps exactly
one definition site. Category filtering is an `EXISTS` against
`transaction_category_split`, never a JOIN: a JOIN would change row
cardinality the moment a transaction has more than one split line, which
would silently double-count a future `SUM` aggregate (P5/P6) wrapped
around this same `Select` — precisely the hazard D16 exists to prevent.
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.transactions.models import Transaction, TransactionCategorySplit


def visible_transactions(
    scope: WorkspaceScope,
    *,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    type: str | None = None,
) -> Select:
    """Design D30's exact shape: JOIN `visible_accounts(scope)` (no
    `archived` kwarg — archiving an account must not make its transaction
    history disappear, mirroring `get_account`'s own reasoning) as a
    subquery, then apply each optional filter only when given.

    `Transaction.workspace_id == scope.workspace_id` is redundant with the
    JOIN and kept anyway: it carries the `(workspace_id, occurred_on
    DESC)` feed index and keeps the scope assertion true even if a future
    phase reassigns an account to a different workspace.
    """
    accounts = visible_accounts(scope).subquery()
    query = (
        sa.select(Transaction)
        .join(accounts, Transaction.account_id == accounts.c.id)
        .where(Transaction.workspace_id == scope.workspace_id)
    )
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if type is not None:
        query = query.where(Transaction.type == type)
    if date_from is not None:
        query = query.where(Transaction.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(Transaction.occurred_on <= date_to)
    if category_id is not None:
        query = query.where(
            sa.exists().where(
                sa.and_(
                    TransactionCategorySplit.transaction_id == Transaction.id,
                    TransactionCategorySplit.category_id == category_id,
                )
            )
        )
    return query
