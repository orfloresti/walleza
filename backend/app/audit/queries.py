"""Read queries for the `audit-log` domain (design D105, spec "Scoped Read
Access" requirement). Two read shapes, matching the two distinct read
routes:

- `visible_audit_log(scope)` — a workspace owner's own-workspace-only read
  (`GET /api/workspace/audit`, `app.workspace.router`), a single
  `workspace_id = scope.workspace_id` predicate. That single predicate is
  also what makes the O3 cross-visibility rule work for free: a
  platform-admin action recorded against THIS workspace carries this same
  `workspace_id`, so it is visible here with no special-casing for actor
  identity at all.
- `all_audit_log(db)` — the platform admin's unfiltered read
  (`GET /api/admin/audit`, `app.admin.router`), every row.

Lives in `app/audit/queries.py`, NOT `app/admin/queries.py` (design D105
is explicit about this placement): this module is shared by two callers
(`app.workspace.router` and `app.admin.router`), not admin-exclusive cross-
workspace SQL in the sense design D100's import firewall targets.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.deps import WorkspaceScope


@dataclass(frozen=True)
class AuditLogRow:
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_was_platform_admin: bool
    action: str
    target_type: str
    target_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    metadata: dict[str, Any]


def _to_row(entry: AuditLog) -> AuditLogRow:
    return AuditLogRow(
        id=entry.id,
        created_at=entry.created_at,
        actor_user_id=entry.actor_user_id,
        actor_was_platform_admin=entry.actor_was_platform_admin,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        workspace_id=entry.workspace_id,
        metadata=entry.metadata_,
    )


def visible_audit_log(db: Session, *, scope: WorkspaceScope) -> list[AuditLogRow]:
    rows = db.execute(
        sa.select(AuditLog)
        .where(AuditLog.workspace_id == scope.workspace_id)
        .order_by(AuditLog.created_at.desc())
    ).scalars()
    return [_to_row(row) for row in rows]


def all_audit_log(db: Session) -> list[AuditLogRow]:
    rows = db.execute(sa.select(AuditLog).order_by(AuditLog.created_at.desc())).scalars()
    return [_to_row(row) for row in rows]
