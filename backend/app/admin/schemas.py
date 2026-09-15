"""Pydantic request/response models for the platform-admin capabilities
(Phase 8 Unit 3, design D109). Every field here is metadata: identifiers,
timestamps, status flags, and counts — NEVER a financial field (design
"Metadata-Only Visibility" requirement, spec "User list contains no
financial fields" / "Workspace list contains counts, not content"
scenarios).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime
    workspace_id: uuid.UUID | None
    workspace_name: str | None
    is_platform_admin: bool
    is_deactivated: bool


class AdminWorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    is_active: bool


class AdminStatsOut(BaseModel):
    total_users: int
    total_workspaces: int
    total_platform_admins: int
    deactivated_users: int
    deactivated_workspaces: int
