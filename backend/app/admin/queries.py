"""Metadata-only read queries for the platform-admin capabilities
(Phase 8 Unit 3, design D109/O1). This module is the SOLE place in
`app.admin` that queries `app.app_user` / `app.workspace` /
`app.workspace_member` / `app.platform_admin` — it never touches
`app.transactions`, `app.budgets`, `app.categories`, `app.transfers`,
`app.templates`, `app.recurring`, `app.reports`, or `app.accounts`, at
module OR function scope (design D100's import firewall,
`backend/tests/admin/test_authority_isolation.py`).

Every row returned here is metadata: identifiers, timestamps, status
flags, and COUNTS — never a financial amount, balance, or content field
(design "Metadata-Only Visibility" requirement). Workspace item counts
are deliberately limited to MEMBER counts, not account/transaction
counts, so this module never needs to reference a financial table at
all — not even via the local-table-literal escape hatch design D100
describes for aggregate counts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.admin.models import PlatformAdmin
from app.auth.session import app_user_table
from app.workspace.models import Workspace, WorkspaceMember


@dataclass(frozen=True)
class AdminUserRow:
    id: uuid.UUID
    email: str
    created_at: datetime
    workspace_id: uuid.UUID | None
    workspace_name: str | None
    is_platform_admin: bool
    is_deactivated: bool


@dataclass(frozen=True)
class AdminWorkspaceRow:
    id: uuid.UUID
    name: str
    created_at: datetime
    member_count: int
    is_active: bool


@dataclass(frozen=True)
class AdminStats:
    total_users: int
    total_workspaces: int
    total_platform_admins: int
    deactivated_users: int
    deactivated_workspaces: int


def list_users(db: Session) -> list[AdminUserRow]:
    admin_ids = set(db.execute(sa.select(PlatformAdmin.user_id)).scalars().all())
    rows = db.execute(
        sa.select(
            app_user_table.c.id,
            app_user_table.c.email,
            app_user_table.c.created_at,
            app_user_table.c.deactivated_at,
            WorkspaceMember.workspace_id,
            Workspace.name,
        )
        .select_from(app_user_table)
        .outerjoin(WorkspaceMember, WorkspaceMember.user_id == app_user_table.c.id)
        .outerjoin(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .order_by(app_user_table.c.created_at)
    ).all()
    return [
        AdminUserRow(
            id=row.id,
            email=row.email,
            created_at=row.created_at,
            workspace_id=row.workspace_id,
            workspace_name=row.name,
            is_platform_admin=row.id in admin_ids,
            is_deactivated=row.deactivated_at is not None,
        )
        for row in rows
    ]


def list_workspaces(db: Session) -> list[AdminWorkspaceRow]:
    rows = db.execute(
        sa.select(
            Workspace.id,
            Workspace.name,
            Workspace.created_at,
            Workspace.is_active,
            sa.func.count(WorkspaceMember.id).label("member_count"),
        )
        .select_from(Workspace)
        .outerjoin(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .group_by(Workspace.id, Workspace.name, Workspace.created_at, Workspace.is_active)
        .order_by(Workspace.created_at)
    ).all()
    return [
        AdminWorkspaceRow(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            member_count=row.member_count,
            is_active=row.is_active,
        )
        for row in rows
    ]


def get_stats(db: Session) -> AdminStats:
    total_users = db.execute(sa.select(sa.func.count()).select_from(app_user_table)).scalar_one()
    total_workspaces = db.execute(sa.select(sa.func.count()).select_from(Workspace)).scalar_one()
    total_platform_admins = db.execute(
        sa.select(sa.func.count()).select_from(PlatformAdmin)
    ).scalar_one()
    deactivated_users = db.execute(
        sa.select(sa.func.count())
        .select_from(app_user_table)
        .where(app_user_table.c.deactivated_at.is_not(None))
    ).scalar_one()
    deactivated_workspaces = db.execute(
        sa.select(sa.func.count()).select_from(Workspace).where(Workspace.is_active.is_(False))
    ).scalar_one()
    return AdminStats(
        total_users=total_users,
        total_workspaces=total_workspaces,
        total_platform_admins=total_platform_admins,
        deactivated_users=deactivated_users,
        deactivated_workspaces=deactivated_workspaces,
    )
