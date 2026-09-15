"""FastAPI routes for the `workspace-membership` capability (design
D13/D14/D18/D20).

Two routers, mounted separately in `app/main.py`:

- `bootstrap_router` holds ONLY `GET /api/workspace` — the single,
  deliberate exception to the membership gate below, because its entire
  job is to CREATE the `workspace_member` row when one is absent (design
  D13's get-or-create). It depends on `get_current_user` alone.
- `router` holds every other workspace route and is declared
  `APIRouter(dependencies=[Depends(require_membership)])` (design D14) —
  every route added to it inherits the membership check with no per-route
  opt-in required. `backend/tests/test_route_coverage.py` is the
  structural proof that no future route escapes this by accident, with
  `GET /api/workspace` as the one explicitly allow-listed exception.

`GET /api/workspace/summary` (design D16, task 6.5) is defined at the
bottom of this module, on the gated `router` (not `bootstrap_router`) —
computing a total requires an already-resolved `WorkspaceScope`, so there
is no bootstrap-style ordering problem for this route.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.accounts import service as accounts_service
from app.db import get_db
from app.deps import WorkspaceScope, get_current_user, require_membership, require_owner
from app.security import AccessTokenClaims
from app.workspace import schemas, service

bootstrap_router = APIRouter(tags=["workspace"])
router = APIRouter(tags=["workspace"], dependencies=[Depends(require_membership)])


def _to_workspace_out(
    *, workspace_id: uuid.UUID, name: str, caller_user_id: uuid.UUID, db: Session
) -> schemas.WorkspaceOut:
    members = service.list_members(db, workspace_id=workspace_id)
    your_role = next((m.role for m in members if m.user_id == caller_user_id), None)
    assert your_role is not None, "caller must hold a workspace_member row to reach this response"
    return schemas.WorkspaceOut(
        id=workspace_id,
        name=name,
        members=[
            schemas.MemberOut(user_id=m.user_id, email=m.email, joined_at=m.joined_at, role=m.role)
            for m in members
        ],
        your_role=your_role,
    )


@bootstrap_router.get("/api/workspace", response_model=schemas.WorkspaceOut)
def get_workspace(
    claims: AccessTokenClaims = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.WorkspaceOut:
    """Get-or-create (design D13). Deliberately NOT behind
    `require_membership` — see this module's docstring."""
    user_id = uuid.UUID(str(claims.sub))
    workspace = service.get_or_create_workspace(db, user_id=user_id)
    response = _to_workspace_out(
        workspace_id=workspace.id, name=workspace.name, caller_user_id=user_id, db=db
    )
    db.commit()
    return response


@router.patch("/api/workspace", response_model=schemas.WorkspaceOut)
def rename_workspace(
    body: schemas.WorkspaceRenameIn,
    scope: WorkspaceScope = Depends(require_owner),
    db: Session = Depends(get_db),
) -> schemas.WorkspaceOut:
    """Owner-only (design D109 "Owner-Only Actions")."""
    workspace = service.rename_workspace(db, scope=scope, name=body.name)
    response = _to_workspace_out(
        workspace_id=workspace.id, name=workspace.name, caller_user_id=scope.user_id, db=db
    )
    db.commit()
    return response


@router.post("/api/workspace/invites", response_model=schemas.InviteCreateOut, status_code=201)
def create_invite(
    scope: WorkspaceScope = Depends(require_owner),
    db: Session = Depends(get_db),
) -> schemas.InviteCreateOut:
    """Owner-only (design D109 "Owner-Only Actions")."""
    issued = service.generate_invite(db, scope=scope)
    db.commit()
    # The raw token is returned exactly once, embedded in this URL — never
    # persisted anywhere, never present in any later response (design D12,
    # spec RED #7). `/join/<token>` matches the frontend route design D11's
    # "File Changes" section describes for PR4's join page.
    return schemas.InviteCreateOut(id=issued.id, url=f"/join/{issued.token}", expires_at=issued.expires_at)


@router.get("/api/workspace/invites", response_model=list[schemas.InviteListItemOut])
def list_invites(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.InviteListItemOut]:
    invites = service.list_invites(db, scope=scope)
    return [
        schemas.InviteListItemOut(
            id=i.id, expires_at=i.expires_at, accepted_at=i.accepted_at, revoked_at=i.revoked_at
        )
        for i in invites
    ]


@router.delete("/api/workspace/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_owner),
    db: Session = Depends(get_db),
) -> None:
    """Owner-only (design D109 "Owner-Only Actions")."""
    try:
        service.revoke_invite(db, scope=scope, invite_id=invite_id)
    except service.InviteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="invite not found") from exc
    db.commit()


@router.post("/api/workspace/invites/accept", status_code=204)
def accept_invite(
    body: schemas.InviteAcceptIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.accept_invite(db, scope=scope, raw_token=body.token)
    except service.InviteRejectedError as exc:
        # Design D18: identical 404 body for all four rejection modes.
        raise HTTPException(status_code=404, detail="invite rejected") from exc
    except service.WorkspaceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()


@router.post("/api/workspace/transfer-ownership", status_code=204)
def transfer_ownership(
    body: schemas.TransferOwnershipIn,
    scope: WorkspaceScope = Depends(require_owner),
    db: Session = Depends(get_db),
) -> None:
    """Owner-only (design D95/D109)."""
    try:
        service.transfer_ownership(db, scope=scope, new_owner_user_id=body.new_owner_user_id)
    except service.MemberNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="target user is not a member of this workspace"
        ) from exc
    db.commit()


@router.delete("/api/workspace/members/me", status_code=204)
def leave_workspace(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    """Self-removal (design D109 "Self-Removal Is a Distinct Path") — open
    to ANY member, not owner-gated. 409 if the caller is the sole owner
    and other members remain (design D95)."""
    try:
        service.leave_workspace(db, scope=scope)
    except service.LastOwnerError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()


@router.delete("/api/workspace/members/{user_id}", status_code=204)
def remove_member(
    user_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_owner),
    db: Session = Depends(get_db),
) -> None:
    """Owner-only, other-member path (design D109). Self-removal targeting
    the caller's own `user_id` is rejected with 409, pointing at
    `DELETE /api/workspace/members/me`."""
    try:
        service.remove_member(db, scope=scope, target_user_id=user_id)
    except service.SelfRemovalNotAllowedHereError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.MemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail="member not found") from exc
    db.commit()


@router.get("/api/workspace/summary", response_model=schemas.WorkspaceSummaryOut)
def get_summary(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.WorkspaceSummaryOut:
    """Design D16 — read-only, no `db.commit()` (mirrors `list_invites`,
    the other pure-read route on this router)."""
    summary = accounts_service.compute_summary(db, scope=scope)
    return schemas.WorkspaceSummaryOut(
        by_currency=[
            schemas.CurrencyTotalOut(currency=item.currency, total=item.total)
            for item in summary.by_currency
        ],
        grand_total=summary.grand_total,
    )
