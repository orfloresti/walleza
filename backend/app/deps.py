"""Cross-cutting FastAPI dependencies for the workspace/account domain
(design D14): resolving the requester's identity from the access-JWT
cookie, and resolving workspace membership per request rather than
trusting a JWT claim.

`get_current_user` reads the SAME `walleza_access` cookie and the SAME
`app.security.verify_access_token` primitive `app.auth.router` already
uses for `/api/me` — no new auth mechanism is invented here, only reused.

`require_membership` is the ONLY function that can produce a
`WorkspaceScope`. Every scope-aware query helper (e.g.
`app.accounts.queries.visible_accounts`) demands one positionally, so a
query that skips the membership check cannot be constructed — and
`backend/tests/test_route_coverage.py` walks every registered route's
resolved dependency tree and fails the build if a workspace/accounts
endpoint's tree does not include `require_membership`, with a single,
deliberate, explicitly allow-listed exception: `GET /api/workspace`
itself (design D13 — get-or-create must run BEFORE any membership row
is guaranteed to exist, so that one route intentionally depends only on
`get_current_user`).

Resolving membership per request (not a JWT claim) is what closes the
D8 gap called out in the proposal: a removed member's still-valid,
un-reissued access JWT is rejected on the very next request, because
`require_membership` re-reads `workspace_member` on every call instead
of trusting anything baked into the token at issuance time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AccessTokenClaims, TokenError, verify_access_token
from app.workspace.models import WorkspaceMember


def get_current_user(walleza_access: str | None = Cookie(default=None)) -> AccessTokenClaims:
    """401 on a missing cookie or any `TokenError` (bad signature, wrong
    issuer/audience, expiry, missing claim) — mirrors `/api/me`'s own
    rejection behavior in `app.auth.router`, just as a reusable
    dependency instead of inline cookie handling."""
    if not walleza_access:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return verify_access_token(walleza_access)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail="not authenticated") from exc


@dataclass(frozen=True)
class WorkspaceScope:
    """Produced ONLY by `require_membership` — see module docstring."""

    user_id: uuid.UUID
    workspace_id: uuid.UUID


def require_membership(
    claims: AccessTokenClaims = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceScope:
    """403 — not 404 — when the requester holds no `workspace_member` row
    at all. Design D18 reserves 404 for a row that exists but falls
    outside a visibility predicate (`app.accounts.queries.visible_accounts`
    in PR3); "not a member of anything (yet)" is a distinct case, handled
    here, and every non-bootstrap workspace/accounts endpoint depends on
    it (enforced by `backend/tests/test_route_coverage.py`)."""
    user_id = uuid.UUID(str(claims.sub))
    row = db.execute(
        sa.select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=403, detail="not a workspace member")
    return WorkspaceScope(user_id=user_id, workspace_id=row.workspace_id)
