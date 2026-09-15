"""Phase 8 design D106 / Unit 4 task 5: proves `require_platform_admin`
(design D98, the PARALLEL authority path) does NOT compose with the
`require_membership` workspace-lockout check added by this Unit.

A platform admin's own workspace being deactivated must never block them
from calling `/api/admin/*` routes — those routes resolve
`require_platform_admin` only, never `require_membership` (design D98's
own rationale: the two authority surfaces share authentication alone,
never authorization). This is the concrete instance of that structural
guarantee this Unit's own change could plausibly have broken.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_platform_admin_deactivating_own_workspace_does_not_block_admin_routes(
    app_factory, seed_user, grant_platform_admin, db_session
) -> None:
    admin_id = seed_user(email="admin-self-workspace@example.com")
    grant_platform_admin(user_id=admin_id)
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(admin_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        # The admin bootstraps their own personal workspace, exactly like
        # any other user would.
        workspace_response = await client.get(
            "/api/workspace", cookies={"walleza_access": cookie}
        )
        assert workspace_response.status_code == 200
        workspace_id = workspace_response.json()["id"]

        # Deactivate that SAME workspace directly (out-of-band, equivalent
        # to another admin having called
        # POST /api/admin/workspaces/{id}/deactivate).
        db_session.execute(
            sa.text("UPDATE app.workspace SET is_active = false WHERE id = :id"),
            {"id": workspace_id},
        )
        db_session.commit()

        # `/api/admin/*` routes resolve `require_platform_admin`, never
        # `require_membership` — the workspace lockout must not leak
        # across the two authority surfaces.
        stats_response = await client.get("/api/admin/stats", cookies={"walleza_access": cookie})
        users_response = await client.get("/api/admin/users", cookies={"walleza_access": cookie})

    assert stats_response.status_code == 200
    assert users_response.status_code == 200
