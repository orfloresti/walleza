"""Scope-aware query builders for the `report-category-breakdown` and
`report-default-currency` capabilities (design D79, D86). Both functions
compose `app.categories.queries.visible_categories` and
`app.transactions.queries.visible_transactions`/`app.accounts.queries.
visible_accounts` exactly as `app.budgets.queries.budget_spent_totals`
composes them — no new visibility predicate is invented here.
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope
from app.transactions.models import TransactionCategorySplit
from app.transactions.queries import visible_transactions


def category_breakdown_totals(
    scope: WorkspaceScope,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str,
    type: str = "expense",
    account_id: uuid.UUID | None = None,
) -> Select:
    """One flat `GROUP BY split.category_id` over EVERY visible category
    (design D79) — driven from `visible_categories`, not from
    transactions, so a category with zero activity in the range still
    appears in the grouped result with `total = 0` instead of vanishing.

    Every filtering predicate (range, currency, type) lives inside a
    JOIN's `ON` clause, never a trailing `WHERE` — a `WHERE` would drop
    the LEFT JOIN's NULL-filled row for a zero-activity category, making
    it disappear from the result instead of reporting `0` (mirrors
    `app.budgets.queries.budget_spent_totals`'s exact reasoning).

    Returns `(category_id, total)` rows; `total` here is each category's
    OWN spend only — the caller's `roll_up()` (design D80) folds children
    into parents afterward.
    """
    cats = visible_categories(scope).subquery()
    txns = visible_transactions(
        scope, account_id=account_id, date_from=date_from, date_to=date_to
    ).subquery()

    # `is_refund` is checked FIRST: a refund transaction's `type` is
    # still `'expense'` (design D74's own definition), so evaluating the
    # plain-type branch first would shadow every refund. Same ordering
    # `app.budgets.queries.budget_spent_totals` uses.
    signed_amount = sa.case(
        (
            sa.and_(Account.id.is_not(None), txns.c.is_refund.is_(True)),
            -TransactionCategorySplit.amount,
        ),
        (
            sa.and_(Account.id.is_not(None), txns.c.type == type),
            TransactionCategorySplit.amount,
        ),
        else_=0,
    )

    return (
        sa.select(
            cats.c.id.label("category_id"),
            sa.func.coalesce(sa.func.sum(signed_amount), 0).label("total"),
        )
        .select_from(cats)
        .outerjoin(
            TransactionCategorySplit,
            TransactionCategorySplit.category_id == cats.c.id,
        )
        .outerjoin(
            txns,
            txns.c.id == TransactionCategorySplit.transaction_id,
        )
        .outerjoin(
            Account,
            sa.and_(
                Account.id == txns.c.account_id,
                Account.currency == currency,
            ),
        )
        .group_by(cats.c.id)
    )


def trend_totals(
    scope: WorkspaceScope,
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str,
    bucket: str,
    type: str = "expense",
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
) -> Select:
    """Design D83's calendar-aligned bucketed query: `GROUP BY
    date_trunc(:bucket, occurred_on)`. `bucket` MUST already be validated
    against `day|week|month|year` by the caller (`service.resolve_bucket`)
    — this function trusts it verbatim as the `date_trunc` field name.
    Postgres `date_trunc('week', ...)` aligns to ISO Monday, matching
    design D83's rationale exactly.

    Mirrors `category_breakdown_totals`'s exact join shape (split-safe
    SUM, `is_refund`-first `sa.case`, currency as an `ON` predicate) —
    only the grouping key differs. Returns SPARSE rows (`bucket_start`,
    `total`) for buckets that have at least one contributing transaction;
    `service.dense_series()` fills the gaps (design D85).
    """
    txns = visible_transactions(
        scope,
        account_id=account_id,
        category_id=category_id,
        date_from=date_from,
        date_to=date_to,
    ).subquery()

    signed_amount = sa.case(
        (
            sa.and_(Account.id.is_not(None), txns.c.is_refund.is_(True)),
            -TransactionCategorySplit.amount,
        ),
        (
            sa.and_(Account.id.is_not(None), txns.c.type == type),
            TransactionCategorySplit.amount,
        ),
        else_=0,
    )

    bucket_start = sa.func.date_trunc(bucket, txns.c.occurred_on).label("bucket_start")

    return (
        sa.select(
            bucket_start,
            sa.func.coalesce(sa.func.sum(signed_amount), 0).label("total"),
        )
        .select_from(txns)
        .join(
            TransactionCategorySplit,
            TransactionCategorySplit.transaction_id == txns.c.id,
        )
        .outerjoin(
            Account,
            sa.and_(
                Account.id == txns.c.account_id,
                Account.currency == currency,
            ),
        )
        .group_by(bucket_start)
    )


def default_currency_counts(scope: WorkspaceScope) -> Select:
    """Design D86's exact query: `Account.currency` grouped by the count
    of transactions on that account, tie-broken by the earliest-created
    account among tied currencies, then `currency` ASC as a final,
    total-order tiebreak so the result is deterministic even with
    identical timestamps.

    Driving from `visible_accounts` (not transactions) via a LEFT JOIN
    means a brand-new workspace with an account and zero transactions
    still returns that account's currency instead of an empty result —
    `default_currency()` in `app.reports.service` reads row 0.
    """
    accounts = visible_accounts(scope).subquery()
    txns = visible_transactions(scope).subquery()

    return (
        sa.select(
            accounts.c.currency.label("currency"),
            sa.func.count(txns.c.id).label("n"),
            sa.func.min(accounts.c.created_at).label("first_account"),
        )
        .select_from(accounts)
        .outerjoin(txns, txns.c.account_id == accounts.c.id)
        .group_by(accounts.c.currency)
        .order_by(
            sa.desc("n"),
            sa.asc("first_account"),
            sa.asc(accounts.c.currency),
        )
    )
