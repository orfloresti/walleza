"""RED -> GREEN, Phase 8 design D95 "Last Owner Cannot Leave or Be
Removed" (tasks.md task 1.8): a sole owner with other members present is
blocked (409) from leaving; a sole owner who is also the workspace's only
member may still leave (existing, unchanged solo-workspace behavior).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_sole_owner_blocked_from_leaving_while_other_members_remain(
    seed_user, app_factory
) -> None:
    owner_id = seed_user(email="owner-sole-blocked@example.com")
    member_id = seed_user(email="member-sole-blocked@example.com")
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

        leave_response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": owner_cookie}
        )
        other_removal_response = await client.delete(
            f"/api/workspace/members/{owner_id}", cookies={"walleza_access": owner_cookie}
        )
        ws_after = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})

    assert leave_response.status_code == 409
    assert other_removal_response.status_code == 409
    assert ws_after.json()["your_role"] == "owner"
    emails = {m["email"] for m in ws_after.json()["members"]}
    assert emails == {"owner-sole-blocked@example.com", "member-sole-blocked@example.com"}


async def test_sole_owner_in_single_member_workspace_may_leave(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    owner_id = seed_user(email="owner-solo-may-leave@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_before = await client.get(
            "/api/workspace", cookies={"walleza_access": owner_cookie}
        )
        workspace_id = workspace_before.json()["id"]

        response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": owner_cookie}
        )

    assert response.status_code == 204

    # Design D95: "nothing is orphaned" — the sole owner's solo workspace
    # is deleted, not left behind as an empty, ownerless row.
    with workspace_db_sessionmaker() as session:
        remaining = session.execute(
            sa.text("SELECT count(*) FROM app.workspace WHERE id = :id"),
            {"id": workspace_id},
        ).scalar_one()
    assert remaining == 0


async def test_owner_may_leave_after_transferring_ownership(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-leave-after-transfer@example.com")
    member_id = seed_user(email="member-leave-after-transfer@example.com")
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
        transfer = await client.post(
            "/api/workspace/transfer-ownership",
            json={"new_owner_user_id": str(member_id)},
            cookies={"walleza_access": owner_cookie},
        )
        assert transfer.status_code == 204

        leave_response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": owner_cookie}
        )

    assert leave_response.status_code == 204
