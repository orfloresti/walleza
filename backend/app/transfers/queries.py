"""Scope-aware query builder for the `transfer-management` capability
(design D38). `visible_transfers` is the ONLY sanctioned way to build a
transfer-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.transactions.queries.visible_transactions`
(design D14's second structural layer: a scopeless query is unwritable).

A transfer names TWO accounts, so this is the one genuinely new query
shape in the codebase: `visible_accounts(scope)` is called TWICE and
`.subquery()`d TWICE, producing two DISTINCT anonymous aliases (SQLAlchemy
gives each its own `anon_1`/`anon_2` name — no collision, no accidental
self-equality). Both are INNER JOINed, so "visible only if BOTH sides
resolve" (design D38, spec's "Both Accounts Must Resolve" requirement) is
a structural property of the `Select` itself, not a hand-written check —
the asymmetric-leak risk the proposal flagged becomes structurally
unexpressible rather than test-dependent.
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.transfers.models import Transfer


def visible_transfers(
    scope: WorkspaceScope,
    *,
    account_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
) -> Select:
    """Design D38's exact shape. Neither `visible_accounts(scope)` call
    passes `archived` — mirrors `visible_transactions`'s own reasoning:
    archiving an account must not make its transfer history disappear.

    The `account_id` filter (design D39) is `sa.or_` over the transfer's
    OWN `from_account_id`/`to_account_id` columns — never the aliased
    subquery columns, which would couple the user-facing filter to the
    visibility mechanism — applied AFTER both visibility JOINs, so it can
    only ever narrow an already-visible result set, never widen it. An
    account the caller cannot see yields `[]`, never a 404 (no existence
    oracle, mirrors Phase 2 RED test #2)."""
    from_accounts = visible_accounts(scope).subquery()
    to_accounts = visible_accounts(scope).subquery()
    query = (
        sa.select(Transfer)
        .join(from_accounts, Transfer.from_account_id == from_accounts.c.id)
        .join(to_accounts, Transfer.to_account_id == to_accounts.c.id)
        .where(Transfer.workspace_id == scope.workspace_id)
    )
    if account_id is not None:
        query = query.where(
            sa.or_(
                Transfer.from_account_id == account_id,
                Transfer.to_account_id == account_id,
            )
        )
    if date_from is not None:
        query = query.where(Transfer.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(Transfer.occurred_on <= date_to)
    return query
