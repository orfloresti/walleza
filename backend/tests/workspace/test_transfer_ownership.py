"""RED -> GREEN, Phase 8 design D95 (tasks.md task 1.7): `POST
/api/workspace/transfer-ownership` is owner-only and atomically demotes
the caller to `member` while promoting the named target to `owner`. The
target must already be a member of the caller's workspace.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_transfer_ownership_happy_path(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-transfer-ok@example.com")
    member_id = seed_user(email="member-transfer-ok@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
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

        transfer_response = await client.post(
            "/api/workspace/transfer-ownership",
            json={"new_owner_user_id": str(member_id)},
            cookies={"walleza_access": owner_cookie},
        )

        ws_after = await client.get("/api/workspace", cookies={"walleza_access": member_cookie})
        roles = {m["user_id"]: m["role"] for m in ws_after.json()["members"]}

    assert transfer_response.status_code == 204
    assert roles[str(owner_id)] == "member"
    assert roles[str(member_id)] == "owner"
    assert ws_after.json()["your_role"] == "owner"


async def test_transfer_ownership_to_non_member_rejected(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-transfer-nonmember@example.com")
    stranger_id = seed_user(email="stranger-transfer-nonmember@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})

        response = await client.post(
            "/api/workspace/transfer-ownership",
            json={"new_owner_user_id": str(stranger_id)},
            cookies={"walleza_access": owner_cookie},
        )

    assert response.status_code == 404


async def test_member_cannot_transfer_ownership(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-transfer-denied@example.com")
    member_id = seed_user(email="member-transfer-denied@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
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

        response = await client.post(
            "/api/workspace/transfer-ownership",
            json={"new_owner_user_id": str(member_id)},
            cookies={"walleza_access": member_cookie},
        )

    assert response.status_code == 403
