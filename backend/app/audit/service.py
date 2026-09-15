"""`record_audit()` (design D103): the single write path into `audit_log`,
called explicitly and inline by `app.workspace.service`
(owner-gated actions) and `app.admin.service` (every platform-admin
mutating action) — sharing the CALLER's own `Session` and never
`db.commit()`-ing itself. It only ever `db.add()` + `db.flush()`s, so the
audit row is part of the exact same transaction as the mutation it
documents: if that transaction later rolls back, the audit row rolls back
with it (spec "Audit write and mutation are atomic" scenario). This single
fact is why middleware was rejected as a design (design D103's rationale):
middleware runs after commit, too late to share a transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit.actions import AuditAction
from app.audit.models import AuditLog


def record_audit(
    db: Session,
    *,
    actor_user_id: uuid.UUID | None,
    actor_was_platform_admin: bool,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            created_at=datetime.now(UTC),
            actor_user_id=actor_user_id,
            actor_was_platform_admin=actor_was_platform_admin,
            action=action.value,
            target_type=target_type,
            target_id=target_id,
            workspace_id=workspace_id,
            metadata_=metadata or {},
        )
    )
    db.flush()
