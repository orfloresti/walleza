"""Pydantic response model for the `audit-log` domain's two read routes
(`GET /api/workspace/audit`, `GET /api/admin/audit`)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_was_platform_admin: bool
    action: str
    target_type: str
    target_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    metadata: dict[str, Any]
