"""RED -> GREEN, Phase 8 design D96/D109, spec workspace-roles domain
"Owner-Only Actions" requirement (tasks.md task 1.5): `PATCH
/api/workspace`, `POST /api/workspace/invites`, `DELETE
/api/workspace/invites/{id}`, and `DELETE /api/workspace/members/{id}`
(removing someone OTHER than the caller) all require the caller to be the
workspace owner. A plain member is rejected with 403 and no state change.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _bootstrap_owner_and_member(client, owner_cookie: str, member_cookie: str) -> str:
    await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
    await client.get("/api/workspace", cookies={"walleza_access": member_cookie})
    invite = await client.post("/api/workspace/invites", cookies={"walleza_access": owner_cookie})
    token = invite.json()["url"].rsplit("/", 1)[-1]
    accept = await client.post(
        "/api/workspace/invites/accept",
        json={"token": token},
        cookies={"walleza_access": member_cookie},
    )
    assert accept.status_code == 204
    owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
    return owner_ws.json()["id"]


async def test_owner_can_rename_workspace(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-rename-ok@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        response = await client.patch(
            "/api/workspace", json={"name": "Renamed"}, cookies={"walleza_access": owner_cookie}
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["your_role"] == "owner"


async def test_member_denied_rename_and_name_unchanged(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-rename-denied@example.com")
    member_id = seed_user(email="member-rename-denied@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _bootstrap_owner_and_member(client, owner_cookie, member_cookie)
        original_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        original_name = original_ws.json()["name"]

        response = await client.patch(
            "/api/workspace", json={"name": "Hijacked"}, cookies={"walleza_access": member_cookie}
        )
        after_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})

    assert response.status_code == 403
    assert after_ws.json()["name"] == original_name
    assert after_ws.json()["your_role"] == "owner"


async def test_member_denied_invite_generation(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-invite-gen-denied@example.com")
    member_id = seed_user(email="member-invite-gen-denied@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _bootstrap_owner_and_member(client, owner_cookie, member_cookie)
        response = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": member_cookie}
        )

    assert response.status_code == 403


async def test_member_denied_invite_revocation(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-invite-revoke-denied@example.com")
    member_id = seed_user(email="member-invite-revoke-denied@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _bootstrap_owner_and_member(client, owner_cookie, member_cookie)
        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        invite_id = invite.json()["id"]

        response = await client.delete(
            f"/api/workspace/invites/{invite_id}", cookies={"walleza_access": member_cookie}
        )

    assert response.status_code == 403


async def test_member_denied_removing_another_member(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-remove-other-denied@example.com")
    member_id = seed_user(email="member-remove-other-denied@example.com")
    third_id = seed_user(email="third-remove-other-denied@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    member_cookie = _cookie_for(member_id)
    third_cookie = _cookie_for(third_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _bootstrap_owner_and_member(client, owner_cookie, member_cookie)
        await client.get("/api/workspace", cookies={"walleza_access": third_cookie})
        third_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        third_token = third_invite.json()["url"].rsplit("/", 1)[-1]
        third_accept = await client.post(
            "/api/workspace/invites/accept",
            json={"token": third_token},
            cookies={"walleza_access": third_cookie},
        )
        assert third_accept.status_code == 204

        response = await client.delete(
            f"/api/workspace/members/{third_id}", cookies={"walleza_access": member_cookie}
        )

    assert response.status_code == 403
