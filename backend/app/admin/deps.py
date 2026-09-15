"""Platform-admin authority dependency (design D98).

`require_platform_admin`/`PlatformAdminContext` is a PARALLEL authority
path to `app.deps.WorkspaceScope`/`require_membership` — it depends ONLY
on `app.deps.get_current_user`, never on `require_membership`, so the two
authority surfaces share authentication alone and never authorization.
See `app/admin/__init__.py` for the structural (test-enforced) guarantees
this shape depends on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin.models import PlatformAdmin
from app.db import get_db
from app.deps import get_current_user
from app.security import AccessTokenClaims


@dataclass(frozen=True)
class PlatformAdminContext:
    """Carries ONLY `user_id` — deliberately NO `workspace_id` field
    anywhere in this shape (design D98). There is no field here for
    workspace-scoped code to read, so this context cannot be accidentally
    threaded into a scoped helper and silently "work"; it is cross-
    workspace by construction, not by convention."""

    user_id: uuid.UUID


def require_platform_admin(
    claims: AccessTokenClaims = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlatformAdminContext:
    """403 "not a platform administrator" when the caller holds no
    `platform_admin` row. Re-resolved from the database on every request
    — never cached on the JWT — so a revoked admin loses access on the
    very next call (mirrors `app.deps.require_owner`'s own re-resolution
    rule).

    Deactivated-user enforcement (`app_user.deactivated_at`, design D101)
    is deferred to Phase 8 Unit 4: that column does not exist yet at this
    Unit. This dependency's shape (a single DB round trip keyed on
    `user_id`) makes adding that predicate later a one-line change to the
    WHERE clause, not a new dependency."""
    user_id = uuid.UUID(str(claims.sub))
    row = db.execute(
        sa.select(PlatformAdmin.user_id).where(PlatformAdmin.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=403, detail="not a platform administrator")
    return PlatformAdminContext(user_id=user_id)
