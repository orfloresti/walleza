"""Scope-aware query builder for the `budget-management` capability
(design D70). `visible_budgets` is the ONLY sanctioned way to build a
budget-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.accounts.queries.visible_accounts` and
`app.categories.queries.visible_categories`'s structural guarantee (design
D14's second layer: a scopeless query is unwritable).

A `Budget` row carries `workspace_id` directly (unlike `Transaction`,
which inherits visibility only through its account), so the workspace leg
is a direct predicate. But an account-scoped budget (`account_id` set)
must not leak a personal account the caller cannot see — so the account
leg reuses `app.accounts.queries.visible_accounts(scope)` via `EXISTS`,
never a JOIN (design D16's cardinality rule, reused here exactly as
`visible_transactions` reuses it for category splits).
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.budgets.models import Budget
from app.deps import WorkspaceScope
from app.transactions.models import TransactionCategorySplit
from app.transactions.queries import visible_transactions


def visible_budgets(
    scope: WorkspaceScope,
    *,
    category_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
) -> Select:
    """`Budget.workspace_id == scope.workspace_id` plus, for any budget
    whose `account_id` is set, an `EXISTS` check against
    `visible_accounts(scope)` (design D70's exact predicate, defined
    exactly once). A budget with `account_id IS NULL` is category-only
    and always passes the account leg.

    `category_id`/`account_id`, when given, additionally filter the
    result to that exact value — used by the service layer to check for
    conflicting/duplicate lookups without hand-rolling a second query
    path."""
    accounts = visible_accounts(scope).subquery()
    query = sa.select(Budget).where(
        Budget.workspace_id == scope.workspace_id,
        sa.or_(
            Budget.account_id.is_(None),
            sa.exists().where(accounts.c.id == Budget.account_id),
        ),
    )
    if category_id is not None:
        query = query.where(Budget.category_id == category_id)
    if account_id is not None:
        query = query.where(Budget.account_id == account_id)
    return query


def budget_spent_totals(
    scope: WorkspaceScope,
    *,
    period_start: datetime.date,
    period_end: datetime.date,
    budget_id: uuid.UUID | None = None,
) -> Select:
    """One grouped aggregate over every visible budget (design D78) — a
    single query, never a per-budget loop. Optionally narrowed to one
    `budget_id` (used by `get_budget`'s single-budget progress read, so the
    exact same SUM expression backs both call sites — design D71/D72/D74).

    Returns `(budget_id, spent)` rows. A budget with zero matching
    transactions in the period still appears (LEFT JOIN all the way
    through), with `spent` coalesced to `0`.

    Join shape, mirroring `visible_transactions`'s own EXISTS-not-JOIN
    warning (D16's cardinality rule) but INTENTIONALLY joining here: the
    join to `transaction_category_split` is re-filtered on the BUDGET's
    `category_id` (design D71) so a multi-category split transaction only
    contributes its own category's split line, never the whole
    transaction amount and never another budget's allocation.
    """
    budgets = visible_budgets(scope).subquery()
    txns = visible_transactions(scope, date_from=period_start, date_to=period_end).subquery()

    # Every filtering predicate below lives INSIDE a join's `ON` clause,
    # never a trailing `WHERE` — a `WHERE` would drop the LEFT JOIN's
    # NULL-filled row for a budget with zero matching transactions,
    # making that budget vanish from the grouped result instead of
    # reporting `spent = 0`. Currency/category mismatches instead resolve
    # to a NULL `TransactionCategorySplit.amount`/`Account.id`, which
    # `sa.case`'s guard turns into a `0` contribution that SQL's `SUM`
    # already ignores.
    signed_amount = sa.case(
        # `is_refund` is checked FIRST: a refund transaction's `type` is
        # still `'expense'` (design D74's own definition — `is_refund` is
        # a flag on an expense, not a third `type` value), so evaluating
        # the plain-expense branch first would shadow every refund.
        (
            sa.and_(Account.id.is_not(None), txns.c.is_refund.is_(True)),
            -TransactionCategorySplit.amount,
        ),
        (
            sa.and_(Account.id.is_not(None), txns.c.type == "expense"),
            TransactionCategorySplit.amount,
        ),
        else_=0,
    )

    query = (
        sa.select(
            budgets.c.id.label("budget_id"),
            sa.func.coalesce(sa.func.sum(signed_amount), 0).label("spent"),
        )
        .select_from(budgets)
        .outerjoin(
            txns,
            sa.or_(
                budgets.c.account_id.is_(None),
                txns.c.account_id == budgets.c.account_id,
            ),
        )
        .outerjoin(
            TransactionCategorySplit,
            sa.and_(
                TransactionCategorySplit.transaction_id == txns.c.id,
                TransactionCategorySplit.category_id == budgets.c.category_id,
            ),
        )
        .outerjoin(
            Account,
            sa.and_(
                Account.id == txns.c.account_id,
                Account.currency == budgets.c.currency,
            ),
        )
        .group_by(budgets.c.id)
    )
    if budget_id is not None:
        query = query.where(budgets.c.id == budget_id)
    return query
