"""Scope-aware query builder for the `category-management` capability
(design D30, decision #7). `visible_categories` is the ONLY sanctioned
way to build a category-scoped `Select`: it takes a `WorkspaceScope` —
which only `app.deps.require_membership` can produce — as its first
positional argument, mirroring `app.accounts.queries.visible_accounts`'s
structural guarantee (design D14's second layer: a scopeless query is
unwritable).

Deliberately simpler than `visible_accounts`: categories are
workspace-scoped and shared, with no personal/owner visibility branch
(decision #7 — nothing in the legacy schema or roadmap suggests private
categories).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.categories.models import Category
from app.deps import WorkspaceScope


def visible_categories(scope: WorkspaceScope) -> Select:
    """`Category.workspace_id == scope.workspace_id` — decision #7's exact
    predicate, defined exactly once. No `archived`/personal branch: every
    category in the caller's own workspace is visible to every member."""
    return sa.select(Category).where(Category.workspace_id == scope.workspace_id)
