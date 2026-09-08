"""GREEN, real end-to-end proof for design D15 / decision 4 (member
removal): `DELETE /api/workspace/members/{user_id}` deletes ONLY the
`workspace_member` row. The removed member's own account rows — shared
or personal — are retained, unmatched, never deleted.

Full cross-member VISIBILITY of a departed member's retained personal
account (spec RED #12) is proven by PR3's `test_visibility.py` once
`visible_accounts`/the accounts endpoints exist (tasks.md task 5.4); this
test proves the narrower, PR2-owned claim: the removal endpoint itself
never touches `app.account` at all.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_member_removal_deletes_only_the_membership_row_accounts_survive(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    owner_id = seed_user(email="owner-removal@example.com")
    peer_id = seed_user(email="peer-removal@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    peer_cookie = _cookie_for(peer_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        workspace_id = owner_ws.json()["id"]
        await client.get("/api/workspace", cookies={"walleza_access": peer_cookie})

        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        token = invite.json()["url"].rsplit("/", 1)[-1]
        accept = await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": peer_cookie},
        )
        assert accept.status_code == 204

        after_accept_ws = await client.get(
            "/api/workspace", cookies={"walleza_access": owner_cookie}
        )
        emails = {m["email"] for m in after_accept_ws.json()["members"]}
        assert emails == {"owner-removal@example.com", "peer-removal@example.com"}

        # `peer` (the removed-to-be member) creates a personal account in
        # the now-shared workspace before being removed.
        with workspace_db_sessionmaker() as session:
            session.execute(
                sa.text(
                    "INSERT INTO app.account "
                    "(id, workspace_id, owner_user_id, name, currency, is_personal) "
                    "VALUES (gen_random_uuid(), :wsid, :owner, 'Peer Personal', 'USD', true)"
                ),
                {"wsid": workspace_id, "owner": peer_id},
            )
            session.commit()

        remove_response = await client.delete(
            f"/api/workspace/members/{peer_id}", cookies={"walleza_access": owner_cookie}
        )

    assert remove_response.status_code == 204

    with workspace_db_sessionmaker() as session:
        member_row = session.execute(
            sa.text(
                "SELECT 1 FROM app.workspace_member WHERE workspace_id = :wsid AND user_id = :uid"
            ),
            {"wsid": workspace_id, "uid": peer_id},
        ).first()
        account_row = session.execute(
            sa.text(
                "SELECT owner_user_id FROM app.account "
                "WHERE workspace_id = :wsid AND owner_user_id = :uid"
            ),
            {"wsid": workspace_id, "uid": peer_id},
        ).first()

    assert member_row is None, "the workspace_member row must be deleted"
    assert account_row is not None, "the removed member's account row must be retained, not deleted"
    assert str(account_row.owner_user_id) == str(peer_id)


async def test_removing_an_unknown_member_returns_404(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-removal-404@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        response = await client.delete(
            f"/api/workspace/members/{uuid.uuid4()}", cookies={"walleza_access": owner_cookie}
        )

    assert response.status_code == 404
