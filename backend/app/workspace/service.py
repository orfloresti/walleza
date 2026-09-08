"""Business logic for the `workspace-membership` capability: get-or-create
onboarding (D13), invite issue/accept/revoke (D12/D18/D20), and member
list/remove/leave (D15's "removal deletes only the join row").

No SQL string-building beyond what a plain SQLAlchemy Core/ORM statement
already gives; every function here takes an already-authorized
`app.deps.WorkspaceScope` (or, for the one bootstrap case, a bare
`user_id`) — this module never resolves membership itself, that is
`app.deps.require_membership`'s job alone.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.session import app_user_table, get_user_by_id
from app.config import get_settings
from app.deps import WorkspaceScope
from app.workspace.models import Workspace, WorkspaceInvite, WorkspaceMember


class InviteRejectedError(Exception):
    """Raised for ANY of the four invite-acceptance failure modes (unknown,
    expired, already-accepted, revoked). Deliberately a single exception
    type/message — design D18 requires all four to produce an identical
    404 body, denying an attacker a token oracle (mirrors
    `app.security.TokenError`'s own "treat every failure identically"
    rule)."""


class WorkspaceConflictError(Exception):
    """Raised when accept-invite is attempted while the accepter's current
    workspace is not solo-and-empty (design D20) -> 409."""


class MemberNotFoundError(Exception):
    """Raised when the target of a member removal holds no
    `workspace_member` row in the caller's own workspace -> 404."""


class InviteNotFoundError(Exception):
    """Raised when an invite-id targeted for revocation/listing does not
    belong to the caller's own workspace -> 404."""


@dataclass(frozen=True)
class IssuedInvite:
    id: uuid.UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class MemberRow:
    user_id: uuid.UUID
    email: str
    joined_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_token(raw_token: str) -> str:
    # Mirrors design D8's `refresh_hash` pattern: the raw token only ever
    # exists in the one-time response body; only its sha256 is persisted.
    return hashlib.sha256(raw_token.encode("ascii")).hexdigest()


# --- bootstrap: get-or-create (design D13) ----------------------------------


def get_or_create_workspace(db: Session, *, user_id: uuid.UUID) -> Workspace:
    """`GET /api/workspace`'s core logic. Absent membership, creates a solo
    workspace named from the user's email and one `workspace_member` row,
    in one transaction. `uq_workspace_member_user_id` (PR1's migration) is
    the real backstop against a concurrent double-create race: if a second,
    concurrent caller wins the unique-constraint race, the losing
    transaction's own half-built workspace is discarded (`db.rollback()`)
    and the winner's row is re-read instead (spec RED #11)."""
    existing = db.execute(
        sa.select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    ).first()
    if existing is not None:
        workspace = db.get(Workspace, existing.workspace_id)
        assert workspace is not None
        return workspace

    user = get_user_by_id(db, user_id=str(user_id))
    # `get_current_user` already proved the JWT `sub` decodes to a real
    # signed token; the row it names is only ever absent here if the
    # underlying app_user was deleted out of band, which is out of scope
    # for Phase 1 (design's "Data Flow" note) — surfacing a clear error
    # beats a confusing None-attribute crash deeper in this function.
    if user is None:
        raise LookupError(f"no app_user row for id {user_id}")

    now = _now()
    workspace = Workspace(
        id=uuid.uuid4(),
        name=f"{user['email']}'s workspace",
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(workspace)
    try:
        db.flush()
        db.add(WorkspaceMember(id=uuid.uuid4(), workspace_id=workspace.id, user_id=user_id, joined_at=now))
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.execute(
            sa.select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
        ).first()
        assert existing is not None, "unique-constraint violation must mean a row now exists"
        workspace = db.get(Workspace, existing.workspace_id)
        assert workspace is not None
        return workspace

    return workspace


def list_members(db: Session, *, workspace_id: uuid.UUID) -> list[MemberRow]:
    rows = db.execute(
        sa.select(WorkspaceMember.user_id, app_user_table.c.email, WorkspaceMember.joined_at)
        .join(app_user_table, app_user_table.c.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.joined_at)
    ).all()
    return [MemberRow(user_id=row.user_id, email=row.email, joined_at=row.joined_at) for row in rows]


def rename_workspace(db: Session, *, scope: WorkspaceScope, name: str) -> Workspace:
    workspace = db.get(Workspace, scope.workspace_id)
    assert workspace is not None
    workspace.name = name
    workspace.updated_at = _now()
    db.flush()
    return workspace


# --- invites (design D12/D18/D20) -------------------------------------------


def generate_invite(db: Session, *, scope: WorkspaceScope) -> IssuedInvite:
    settings = get_settings()
    now = _now()
    raw_token = secrets.token_urlsafe(32)
    invite = WorkspaceInvite(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        created_by_user_id=scope.user_id,
        token_hash=_hash_token(raw_token),
        expires_at=now + timedelta(days=settings.invite_ttl_days),
        created_at=now,
    )
    db.add(invite)
    db.flush()
    return IssuedInvite(id=invite.id, token=raw_token, expires_at=invite.expires_at)


def list_invites(db: Session, *, scope: WorkspaceScope) -> list[WorkspaceInvite]:
    """No raw token anywhere in this result set — only ever `token_hash`,
    which the router's schema layer deliberately never serializes either
    (spec RED #7, belt and suspenders)."""
    return list(
        db.execute(
            sa.select(WorkspaceInvite)
            .where(WorkspaceInvite.workspace_id == scope.workspace_id)
            .order_by(WorkspaceInvite.created_at.desc())
        ).scalars()
    )


def revoke_invite(db: Session, *, scope: WorkspaceScope, invite_id: uuid.UUID) -> None:
    invite = db.execute(
        sa.select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id, WorkspaceInvite.workspace_id == scope.workspace_id
        )
    ).scalar_one_or_none()
    if invite is None:
        raise InviteNotFoundError("invite not found in this workspace")
    invite.revoked_at = _now()
    db.flush()


def accept_invite(db: Session, *, scope: WorkspaceScope, raw_token: str) -> None:
    """Design D20: accept is allowed only when the accepter's CURRENT
    workspace is solo (exactly one member: the accepter) AND empty (zero
    accounts) — that workspace is then deleted in the same transaction and
    membership moves to the invite's workspace. Otherwise 409, and no
    membership row is written.

    Invite validity (unknown / expired / already-accepted / revoked) is
    checked FIRST, before the D20 conflict check, so an attacker probing
    with a bad token never learns anything about the conflict state of
    the account they authenticated as (spec RED #5/#6)."""
    token_hash = _hash_token(raw_token)
    invite = db.execute(
        sa.select(WorkspaceInvite).where(WorkspaceInvite.token_hash == token_hash)
    ).scalar_one_or_none()

    now = _now()
    if (
        invite is None
        or invite.revoked_at is not None
        or invite.accepted_at is not None
        or invite.expires_at < now
    ):
        raise InviteRejectedError("invite is invalid, expired, or already consumed")

    member_count = db.execute(
        sa.select(sa.func.count())
        .select_from(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == scope.workspace_id)
    ).scalar_one()
    # Local import: `app.accounts.models` never imports anything from
    # `app.workspace`, so there is no real cycle risk, but keeping this
    # one cross-feature-module reference local documents the dependency
    # explicitly at its single point of use instead of at module load time.
    from app.accounts.models import Account

    account_count = db.execute(
        sa.select(sa.func.count())
        .select_from(Account)
        .where(Account.workspace_id == scope.workspace_id)
    ).scalar_one()
    if member_count > 1 or account_count > 0:
        raise WorkspaceConflictError(
            "current workspace must be solo and empty before accepting a new invite"
        )

    old_workspace_id = scope.workspace_id
    db.execute(sa.delete(WorkspaceMember).where(WorkspaceMember.workspace_id == old_workspace_id))
    db.add(
        WorkspaceMember(
            id=uuid.uuid4(), workspace_id=invite.workspace_id, user_id=scope.user_id, joined_at=now
        )
    )
    invite.accepted_at = now
    invite.accepted_by_user_id = scope.user_id
    db.flush()
    db.execute(sa.delete(Workspace).where(Workspace.id == old_workspace_id))
    db.flush()


# --- membership (design D15's "removal deletes only the join row") ---------


def remove_member(db: Session, *, scope: WorkspaceScope, target_user_id: uuid.UUID) -> None:
    """Deletes ONLY the `workspace_member` row. Never touches `account`
    rows: a removed member's personal accounts stay exactly where they
    are, retained and simply unreachable through `visible_accounts` from
    then on (decision 4 / design D15)."""
    result = db.execute(
        sa.delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == scope.workspace_id,
            WorkspaceMember.user_id == target_user_id,
        )
    )
    if result.rowcount == 0:
        raise MemberNotFoundError("member not found in this workspace")
