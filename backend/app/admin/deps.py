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
from app.auth.session import app_user_table
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

    Phase 8 design D101: also joins to `app_user.deactivated_at` and 403s
    if the admin's own account is deactivated — a deactivated user must
    not retain platform authority, even if their `platform_admin` row is
    still present."""
    user_id = uuid.UUID(str(claims.sub))
    row = db.execute(
        sa.select(PlatformAdmin.user_id, app_user_table.c.deactivated_at)
        .join(app_user_table, app_user_table.c.id == PlatformAdmin.user_id)
        .where(PlatformAdmin.user_id == user_id)
    ).first()
    if row is None or row.deactivated_at is not None:
        raise HTTPException(status_code=403, detail="not a platform administrator")
    return PlatformAdminContext(user_id=user_id)
