"""Scope-aware query builder for the `recurring-transactions` capability
(design D45-D56). `visible_recurring` is the ONLY sanctioned way to build a
recurrence-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.transactions.queries.visible_transactions`
(design D14's second structural layer: a scopeless query is unwritable).

This is the CRUD-facing, scope-aware query — distinct from the
cross-workspace, scopeless due-detection scan a later PR's
`app.recurring.generation` performs directly against `RecurringTransaction`
(design's Data Flow ①, deliberately outside any `WorkspaceScope`).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.recurring.models import RecurringTransaction


def visible_recurring(
    scope: WorkspaceScope,
    *,
    account_id: uuid.UUID | None = None,
    is_subscription: bool | None = None,
) -> Select:
    """JOIN `visible_accounts(scope)` (no `archived` kwarg, mirrors
    `visible_transactions`) as a subquery. `is_subscription`, when given,
    is the Subscriptions view's exact filter (spec: "the recurrence list
    filtered by `is_subscription=true`" — no separate resource)."""
    accounts = visible_accounts(scope).subquery()
    query = (
        sa.select(RecurringTransaction)
        .join(accounts, RecurringTransaction.account_id == accounts.c.id)
        .where(RecurringTransaction.workspace_id == scope.workspace_id)
    )
    if account_id is not None:
        query = query.where(RecurringTransaction.account_id == account_id)
    if is_subscription is not None:
        query = query.where(RecurringTransaction.is_subscription.is_(is_subscription))
    return query
