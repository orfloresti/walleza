"""FastAPI routes for the platform-admin capabilities (Phase 8 Unit 3,
design D109). `APIRouter(dependencies=[Depends(require_platform_admin)])`
mirrors `app.workspace.router`'s `router` (gate inherited by every route,
no per-route opt-in) — the INVERSE of that router's gate: this one MUST
NEVER resolve `require_membership` anywhere in its dependency tree
(`backend/tests/test_route_coverage.py`'s
`test_every_admin_route_requires_platform_admin_only`, design D108).

This module imports `PlatformAdminContext`/`require_platform_admin` only
— never `app.deps.WorkspaceScope`/`require_membership` (design D99, the
"no dual-context route" guarantee) — and never a financial-domain module
(design D100's import firewall, enforced package-wide by
`backend/tests/admin/test_authority_isolation.py`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin import queries, schemas, service
from app.admin.deps import PlatformAdminContext, require_platform_admin
from app.db import get_db

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)]
)


@router.get("/users", response_model=list[schemas.AdminUserOut])
def list_users(db: Session = Depends(get_db)) -> list[schemas.AdminUserOut]:
    rows = queries.list_users(db)
    return [
        schemas.AdminUserOut(
            id=row.id,
            email=row.email,
            created_at=row.created_at,
            workspace_id=row.workspace_id,
            workspace_name=row.workspace_name,
            is_platform_admin=row.is_platform_admin,
            is_deactivated=row.is_deactivated,
        )
        for row in rows
    ]


@router.get("/workspaces", response_model=list[schemas.AdminWorkspaceOut])
def list_workspaces(db: Session = Depends(get_db)) -> list[schemas.AdminWorkspaceOut]:
    rows = queries.list_workspaces(db)
    return [
        schemas.AdminWorkspaceOut(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            member_count=row.member_count,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.get("/stats", response_model=schemas.AdminStatsOut)
def get_stats(db: Session = Depends(get_db)) -> schemas.AdminStatsOut:
    stats = queries.get_stats(db)
    return schemas.AdminStatsOut(
        total_users=stats.total_users,
        total_workspaces=stats.total_workspaces,
        total_platform_admins=stats.total_platform_admins,
        deactivated_users=stats.deactivated_users,
        deactivated_workspaces=stats.deactivated_workspaces,
    )


@router.post("/users/{user_id}/deactivate", status_code=204)
def deactivate_user(
    user_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.deactivate_user(db, admin=ctx, target_user_id=user_id)
    except service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    db.commit()


@router.post("/users/{user_id}/reactivate", status_code=204)
def reactivate_user(
    user_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.reactivate_user(db, admin=ctx, target_user_id=user_id)
    except service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    db.commit()


@router.post("/workspaces/{workspace_id}/deactivate", status_code=204)
def deactivate_workspace(
    workspace_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.deactivate_workspace(db, admin=ctx, target_workspace_id=workspace_id)
    except service.WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    db.commit()


@router.post("/workspaces/{workspace_id}/reactivate", status_code=204)
def reactivate_workspace(
    workspace_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.reactivate_workspace(db, admin=ctx, target_workspace_id=workspace_id)
    except service.WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workspace not found") from exc
    db.commit()


@router.post("/admins/{user_id}", status_code=204)
def grant_admin(
    user_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.grant_admin(db, admin=ctx, target_user_id=user_id)
    except service.UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail="user not found") from exc
    except service.AlreadyAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()


@router.delete("/admins/{user_id}", status_code=204)
def revoke_admin(
    user_id: uuid.UUID,
    ctx: PlatformAdminContext = Depends(require_platform_admin),
    db: Session = Depends(get_db),
) -> None:
    """Self-revocation allowed (design O6) — `user_id == ctx.user_id` is
    not special-cased; `service.revoke_admin` performs the ordinary
    delete regardless of whose row it is."""
    try:
        service.revoke_admin(db, admin=ctx, target_user_id=user_id)
    except service.NotAdminError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
