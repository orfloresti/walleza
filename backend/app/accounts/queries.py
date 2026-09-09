"""Scope-aware query builder for the `account-visibility` capability
(design D15). `visible_accounts` is the ONLY sanctioned way to build an
account-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, so a caller cannot construct a scoped account query without
having already passed the membership check (design D14's second
structural layer: a scopeless query is unwritable).

Full account CRUD (`app/accounts/service.py`, `app/accounts/router.py`,
`app/accounts/schemas.py`) and `GET /api/workspace/summary` (design D16)
are built on top of this single function — see
`sdd/phase-1-workspace-users-accounts/tasks` Phase 5/6 (PR3).

Phase 2's `transaction-visibility` capability (design D30) formalizes this
function as a REUSABLE BASE `Select`: `app.transactions.queries.
visible_transactions(scope, ...)` JOINs the exact `Select` this function
returns (called with no `archived` kwarg) as a subquery, rather than
duplicating the personal-account predicate. This is a reuse-contract
clarification only — every existing account-visibility guarantee (owner-
only personal account visibility, list, direct lookup, balance
aggregation) holds exactly as before; nothing below changed behavior for
Phase 2.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.models import Account
from app.deps import WorkspaceScope


def visible_accounts(scope: WorkspaceScope, *, archived: bool | None = None) -> Select:
    """`Account.workspace_id == scope.workspace_id AND (NOT is_personal OR
    owner_user_id == scope.user_id)` — design D15's exact predicate,
    defined exactly once.

    A departed member's personal accounts match no current scope: once
    their own `workspace_member` row is gone, `require_membership` never
    yields a `WorkspaceScope` for that workspace again on their behalf, so
    the row is retained (never deleted — decision 4) but permanently
    unreachable through this query, and through it alone.

    `archived`, when given, additionally filters to exactly that archived
    state (decision 6: `archived` is the one collapsed lifecycle flag —
    there is no separate hide state to filter on separately). `None` (the
    default) applies no archived filtering, preserving this function's
    original unfiltered shape for a caller that wants a match regardless
    of archived state (e.g. `app.accounts.service.get_account` — a direct
    fetch-by-id is not a "listing", so archived state does not gate it).

    `app/accounts/router.py`'s list endpoint passes `archived=False` by
    default and `archived=True` for `?archived=true`. `compute_summary`
    (design D16) passes `archived=False` too — literally the SAME call
    the list endpoint's default makes — so a total cannot count a row the
    default account list would hide.
    """
    query = sa.select(Account).where(
        Account.workspace_id == scope.workspace_id,
        sa.or_(Account.is_personal.is_(False), Account.owner_user_id == scope.user_id),
    )
    if archived is not None:
        query = query.where(Account.archived.is_(archived))
    return query
