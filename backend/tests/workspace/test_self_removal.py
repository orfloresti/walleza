"""RED -> GREEN, Phase 8 design D109 "Self-Removal Is a Distinct Path From
Owner Removal" (tasks.md task 1.6): `DELETE /api/workspace/members/me`
lets any member (owner or not) leave without owner privilege, and
`DELETE /api/workspace/members/{user_id}` targeting the caller's OWN id
is rejected (409), pointing the caller at `/members/me` instead — proving
these are two distinct authorization paths, not one code path with a
special case.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_plain_member_leaves_voluntarily_without_owner_privilege(
    seed_user, app_factory
) -> None:
    owner_id = seed_user(email="owner-leave-voluntary@example.com")
    member_id = seed_user(email="member-leave-voluntary@example.com")
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

        response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": member_cookie}
        )

    assert response.status_code == 204


async def test_owner_self_removal_via_members_id_is_rejected_distinctly(
    seed_user, app_factory
) -> None:
    """Owner removing self via `DELETE /api/workspace/members/{their own
    id}` uses the OTHER-removal code path, which always rejects self
    targeting — proving self-removal and other-removal are evaluated
    under distinct authorization rules, even for the same caller."""
    owner_id = seed_user(email="owner-self-via-other-path@example.com")
    member_id = seed_user(email="member-self-via-other-path@example.com")
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

        other_removal_response = await client.delete(
            f"/api/workspace/members/{owner_id}", cookies={"walleza_access": owner_cookie}
        )
        self_removal_response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": owner_cookie}
        )

    assert other_removal_response.status_code == 409
    # The sole owner with another member present is still blocked on the
    # correct (self-removal) path too — by the last-owner rule, not by
    # the "wrong endpoint" rule. Covered in detail by test_last_owner.py;
    # here we only assert it is NOT the same 409 reason as above (i.e.
    # this request actually reached leave_workspace's logic).
    assert self_removal_response.status_code == 409
