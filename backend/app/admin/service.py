"""Business logic for the platform-admin capabilities (Phase 8 Unit 3,
design D109): deactivate/reactivate user, deactivate/reactivate workspace
(flag-flip only — the read-only LOCKOUT enforcement itself is Unit 4, see
migration `0010`'s docstring), and grant/revoke platform-admin status
(self-revocation allowed, design O6).

Every function here takes an already-resolved `PlatformAdminContext`
(never `WorkspaceScope` — design D99) and talks only to
`app.app_user`/`app.workspace`/`app.platform_admin`, plus
`app.auth.session.revoke_all_sessions_for_user` for session revocation —
never a financial-domain module (design D100's import firewall, enforced
by `backend/tests/admin/test_authority_isolation.py` over this whole
package).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.admin.deps import PlatformAdminContext
from app.admin.models import PlatformAdmin
from app.auth.session import app_user_table, revoke_all_sessions_for_user
from app.workspace.models import Workspace


class UserNotFoundError(Exception):
    """Raised when a target `user_id` holds no `app_user` row -> 404."""


class WorkspaceNotFoundError(Exception):
    """Raised when a target `workspace_id` holds no `app.workspace` row -> 404."""


class AlreadyAdminError(Exception):
    """Raised when granting admin to a user who already holds a
    `platform_admin` row -> 409."""


class NotAdminError(Exception):
    """Raised when revoking admin from a user who holds no `platform_admin`
    row -> 404."""


def _now() -> datetime:
    return datetime.now(UTC)


def _user_exists(db: Session, *, user_id: uuid.UUID) -> bool:
    row = db.execute(
        sa.select(app_user_table.c.id).where(app_user_table.c.id == user_id)
    ).first()
    return row is not None


# --- user deactivation (design "Deactivate/Reactivate User") ---------------


def deactivate_user(db: Session, *, admin: PlatformAdminContext, target_user_id: uuid.UUID) -> None:
    """Sets `app_user.deactivated_at` and revokes every live session for the
    target in the same transaction — a still-valid access JWT cannot be
    refreshed past this point (design D101). Login-path rejection itself is
    Unit 4 (that check lives in the auth/session login flow, not here).

    Audit hook placeholder: Unit 5 (`app/audit/service.record_audit`) will
    call `platform.user_deactivated` from this exact call site once the
    audit-log domain exists; no audit table exists yet in this Unit."""
    if not _user_exists(db, user_id=target_user_id):
        raise UserNotFoundError("no such user")
    db.execute(
        sa.update(app_user_table)
        .where(app_user_table.c.id == target_user_id)
        .values(deactivated_at=_now())
    )
    revoke_all_sessions_for_user(db, user_id=target_user_id)
    # TODO(Unit 5): record_audit(action="platform.user_deactivated", ...)


def reactivate_user(db: Session, *, admin: PlatformAdminContext, target_user_id: uuid.UUID) -> None:
    if not _user_exists(db, user_id=target_user_id):
        raise UserNotFoundError("no such user")
    db.execute(
        sa.update(app_user_table)
        .where(app_user_table.c.id == target_user_id)
        .values(deactivated_at=None)
    )
    # TODO(Unit 5): record_audit(action="platform.user_reactivated", ...)


# --- workspace deactivation (design "Deactivate/Reactivate Workspace") -----


def deactivate_workspace(
    db: Session, *, admin: PlatformAdminContext, target_workspace_id: uuid.UUID
) -> None:
    """Flips `workspace.is_active` to False. The read-only LOCKOUT this flag
    is meant to enforce (blocking member mutations) is wired inside
    `require_membership` in Unit 4 (migration `0010`'s docstring) — this
    Unit only flips the flag, per tasks.md Unit 3 task 3.5."""
    workspace = db.get(Workspace, target_workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError("no such workspace")
    workspace.is_active = False
    db.flush()
    # TODO(Unit 5): record_audit(action="platform.workspace_deactivated", ...)


def reactivate_workspace(
    db: Session, *, admin: PlatformAdminContext, target_workspace_id: uuid.UUID
) -> None:
    workspace = db.get(Workspace, target_workspace_id)
    if workspace is None:
        raise WorkspaceNotFoundError("no such workspace")
    workspace.is_active = True
    db.flush()
    # TODO(Unit 5): record_audit(action="platform.workspace_reactivated", ...)


# --- grant/revoke admin (design "Grant and Revoke Admin", O6) --------------


def grant_admin(db: Session, *, admin: PlatformAdminContext, target_user_id: uuid.UUID) -> None:
    if not _user_exists(db, user_id=target_user_id):
        raise UserNotFoundError("no such user")
    existing = db.get(PlatformAdmin, target_user_id)
    if existing is not None:
        raise AlreadyAdminError("user is already a platform administrator")
    db.add(
        PlatformAdmin(
            user_id=target_user_id,
            granted_at=_now(),
            granted_by_user_id=admin.user_id,
            note=None,
        )
    )
    db.flush()
    # TODO(Unit 5): record_audit(action="platform.admin_granted", ...)


def revoke_admin(db: Session, *, admin: PlatformAdminContext, target_user_id: uuid.UUID) -> None:
    """Self-revocation is explicitly allowed (design O6, spec scenario
    "Self-revocation allowed") — no special-casing here beyond the
    ordinary delete: `admin` (the caller) and `target_user_id` may be the
    same value, and the delete proceeds exactly as it would for any other
    admin. The caller loses `require_platform_admin` access on their VERY
    NEXT request, same as any other revoked admin (design D98's
    per-request re-resolution)."""
    existing = db.get(PlatformAdmin, target_user_id)
    if existing is None:
        raise NotAdminError("user is not a platform administrator")
    db.delete(existing)
    db.flush()
    # TODO(Unit 5): record_audit(action="platform.admin_self_revoked" if
    # target_user_id == admin.user_id else "platform.admin_revoked", ...)
