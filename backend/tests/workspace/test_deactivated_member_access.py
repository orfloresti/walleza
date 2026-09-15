"""RED -> GREEN: sdd/phase-8-admin verify-report WARNING gap closure.

Design D101 states a deactivated user's access must be checked at BOTH
`require_platform_admin` (already enforced) and `require_membership`. This
module proves the second half: a user deactivated mid-session, whose
access JWT is still cryptographically valid (not expired, never
reissued), must be rejected on the very next ordinary workspace-scoped
request — not just on the platform-admin surface.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _deactivate(db_session, *, user_id) -> None:
    db_session.execute(
        sa.text("UPDATE app.app_user SET deactivated_at = now() WHERE id = :uid"),
        {"uid": user_id},
    )
    db_session.commit()


def _reactivate(db_session, *, user_id) -> None:
    db_session.execute(
        sa.text("UPDATE app.app_user SET deactivated_at = NULL WHERE id = :uid"),
        {"uid": user_id},
    )
    db_session.commit()


async def test_deactivated_users_still_valid_access_jwt_is_rejected_on_workspace_route(
    seed_user, app_factory, db_session
) -> None:
    user_id = seed_user(email="deactivated-midsession@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        # Establish membership via the bootstrap get-or-create route while
        # still active.
        first = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        assert first.status_code == 200

        # Deactivated mid-session, out-of-band (e.g. a platform admin
        # action) — the SAME access token, still cryptographically valid
        # and not expired, is never reissued or revoked at the JWT layer.
        _deactivate(db_session, user_id=user_id)

        # Before this fix, `require_membership` never checked
        # `deactivated_at`, so this request would still succeed with 200.
        second = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": cookie}
        )

    assert second.status_code == 403
    assert "expires_at" not in second.text


async def test_reactivated_users_still_valid_access_jwt_works_again_without_relogin(
    seed_user, app_factory, db_session
) -> None:
    user_id = seed_user(email="reactivated-midsession@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        first = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        assert first.status_code == 200

        _deactivate(db_session, user_id=user_id)

        blocked = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": cookie}
        )
        assert blocked.status_code == 403

        # Reactivation restores access on the SAME still-valid token — no
        # re-login required, matching `require_platform_admin`'s own
        # re-resolution-per-request behavior (row is re-read every call,
        # never cached).
        _reactivate(db_session, user_id=user_id)

        restored = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": cookie}
        )

    assert restored.status_code == 200
