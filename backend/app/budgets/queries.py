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

import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.budgets.models import Budget
from app.deps import WorkspaceScope


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
