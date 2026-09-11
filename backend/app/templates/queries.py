"""Scope-aware query builder for the `transaction-templates` capability
(design D45-D56). `visible_templates` is the ONLY sanctioned way to build a
template-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.transactions.queries.visible_transactions`
(design D14's second structural layer: a scopeless query is unwritable).

A template carries no visibility state of its own — its visibility is
entirely inherited from `account_id` via `visible_accounts(scope)`, exactly
like `Transaction` (design's Technical Approach: "clone P2/P3's layering
verbatim").
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.templates.models import TransactionTemplate


def visible_templates(
    scope: WorkspaceScope, *, account_id: uuid.UUID | None = None
) -> Select:
    """JOIN `visible_accounts(scope)` (no `archived` kwarg — an archived
    account's templates must not disappear, mirroring
    `visible_transactions`'s own reasoning) as a subquery, then apply the
    optional `account_id` filter.

    `TransactionTemplate.workspace_id == scope.workspace_id` is redundant
    with the JOIN and kept anyway, mirroring `visible_transactions`'s own
    rationale: it carries the `(workspace_id, position)` ordering index and
    keeps the scope assertion true even if a future phase reassigns an
    account to a different workspace.
    """
    accounts = visible_accounts(scope).subquery()
    query = (
        sa.select(TransactionTemplate)
        .join(accounts, TransactionTemplate.account_id == accounts.c.id)
        .where(TransactionTemplate.workspace_id == scope.workspace_id)
    )
    if account_id is not None:
        query = query.where(TransactionTemplate.account_id == account_id)
    return query
