"""RED -> GREEN, Phase 8 design D109/D110 (tasks.md task 1.9): `MemberOut`
gains `role`, and `GET /api/workspace` gains `your_role` for the caller.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_workspace_response_includes_role_fields(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-schema-role@example.com")
    member_id = seed_user(email="member-schema-role@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": member_cookie})
        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        token = invite.json()["url"].rsplit("/", 1)[-1]
        await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": member_cookie},
        )

        owner_ws_after = await client.get(
            "/api/workspace", cookies={"walleza_access": owner_cookie}
        )
        member_ws_after = await client.get(
            "/api/workspace", cookies={"walleza_access": member_cookie}
        )

    assert owner_ws.json()["your_role"] == "owner"
    assert owner_ws_after.json()["your_role"] == "owner"
    assert member_ws_after.json()["your_role"] == "member"

    roles_by_email = {m["email"]: m["role"] for m in owner_ws_after.json()["members"]}
    assert roles_by_email["owner-schema-role@example.com"] == "owner"
    assert roles_by_email["member-schema-role@example.com"] == "member"
