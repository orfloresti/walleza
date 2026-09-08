"""RED -> GREEN, design D18/D20, spec RED #5/#6/#7 (tasks.md 3.4-3.6):

- All four invite-rejection failure modes (unknown, expired,
  already-accepted, revoked) return an identical 404 body — denying an
  attacker a token oracle (mirrors `app.security.TokenError`'s uniform
  rejection).
- Accepting an invite while the accepter's current workspace is not
  solo-and-empty (peers present, or accounts present) is rejected with
  409, and writes no membership row.
- The raw invite token never appears in any list response, and never
  equals the persisted `token_hash`.
"""

from __future__ import annotations

import hashlib
import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def test_invite_rejection_is_uniform_across_all_four_failure_modes(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    owner_id = seed_user(email="owner-invalid@example.com")
    accepter_id = seed_user(email="accepter-invalid@example.com")
    third_id = seed_user(email="third-invalid@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    accepter_cookie = _cookie_for(accepter_id)
    third_cookie = _cookie_for(third_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": accepter_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": third_cookie})

        # Case 1: unknown token.
        unknown_response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": "totally-unknown-token"},
            cookies={"walleza_access": accepter_cookie},
        )

        # Case 2: expired token.
        expired_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        assert expired_invite.status_code == 201
        expired_token = _token_from_url(expired_invite.json()["url"])
        with workspace_db_sessionmaker() as session:
            session.execute(
                sa.text(
                    "UPDATE app.workspace_invite SET expires_at = now() - interval '1 day' "
                    "WHERE id = :id"
                ),
                {"id": expired_invite.json()["id"]},
            )
            session.commit()
        expired_response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": expired_token},
            cookies={"walleza_access": accepter_cookie},
        )

        # Case 3: already-accepted token — accepter legitimately accepts,
        # then a third user tries the same, now-consumed token.
        consumable_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        consumable_token = _token_from_url(consumable_invite.json()["url"])
        first_accept = await client.post(
            "/api/workspace/invites/accept",
            json={"token": consumable_token},
            cookies={"walleza_access": accepter_cookie},
        )
        assert first_accept.status_code == 204
        already_accepted_response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": consumable_token},
            cookies={"walleza_access": third_cookie},
        )

        # Case 4: revoked token.
        revocable_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        revocable_token = _token_from_url(revocable_invite.json()["url"])
        revoke_response = await client.delete(
            f"/api/workspace/invites/{revocable_invite.json()['id']}",
            cookies={"walleza_access": owner_cookie},
        )
        assert revoke_response.status_code == 204
        revoked_response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": revocable_token},
            cookies={"walleza_access": third_cookie},
        )

    responses = (unknown_response, expired_response, already_accepted_response, revoked_response)
    for response in responses:
        assert response.status_code == 404

    bodies = {response.text for response in responses}
    assert len(bodies) == 1, (
        "all four invite rejection modes must return an IDENTICAL body, got: "
        f"{[r.text for r in responses]}"
    )


async def test_accept_invite_conflicts_when_accepters_workspace_has_accounts(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    owner_id = seed_user(email="owner-conflict-accounts@example.com")
    accepter_id = seed_user(email="accepter-conflict-accounts@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    accepter_cookie = _cookie_for(accepter_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        accepter_ws = await client.get(
            "/api/workspace", cookies={"walleza_access": accepter_cookie}
        )
        accepter_workspace_id = accepter_ws.json()["id"]

        with workspace_db_sessionmaker() as session:
            session.execute(
                sa.text(
                    "INSERT INTO app.account (id, workspace_id, name, currency) "
                    "VALUES (gen_random_uuid(), :wsid, 'Existing', 'USD')"
                ),
                {"wsid": accepter_workspace_id},
            )
            session.commit()

        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        token = _token_from_url(invite.json()["url"])

        response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": accepter_cookie},
        )

    assert response.status_code == 409

    with workspace_db_sessionmaker() as session:
        member_row = session.execute(
            sa.text("SELECT workspace_id FROM app.workspace_member WHERE user_id = :uid"),
            {"uid": accepter_id},
        ).first()
    assert member_row is not None
    assert str(member_row.workspace_id) == accepter_workspace_id, (
        "no membership row must be written on a 409 conflict"
    )


async def test_accept_invite_conflicts_when_accepters_workspace_has_peers(
    seed_user, app_factory
) -> None:
    owner_id = seed_user(email="owner-conflict-peers@example.com")
    peer_id = seed_user(email="peer-conflict-peers@example.com")
    accepter_id = seed_user(email="accepter-conflict-peers@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)
    peer_cookie = _cookie_for(peer_id)
    accepter_cookie = _cookie_for(accepter_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": peer_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": accepter_cookie})

        # `peer` joins `accepter`'s own workspace first, so `accepter`'s
        # workspace is no longer solo when `accepter` later tries to
        # accept a SEPARATE invite below.
        peer_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": accepter_cookie}
        )
        peer_token = _token_from_url(peer_invite.json()["url"])
        peer_accept = await client.post(
            "/api/workspace/invites/accept",
            json={"token": peer_token},
            cookies={"walleza_access": peer_cookie},
        )
        assert peer_accept.status_code == 204

        owner_invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        owner_token = _token_from_url(owner_invite.json()["url"])

        response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": owner_token},
            cookies={"walleza_access": accepter_cookie},
        )

    assert response.status_code == 409


async def test_raw_invite_token_never_appears_in_list_response_or_equals_stored_hash(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    owner_id = seed_user(email="tokentest@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_cookie = _cookie_for(owner_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        created = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        assert created.status_code == 201
        raw_token = _token_from_url(created.json()["url"])

        listed = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )

    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert "token" not in body[0]
    assert "url" not in body[0]
    assert raw_token not in listed.text

    with workspace_db_sessionmaker() as session:
        stored_hash = session.execute(
            sa.text("SELECT token_hash FROM app.workspace_invite WHERE id = :id"),
            {"id": created.json()["id"]},
        ).scalar_one()

    assert stored_hash != raw_token
    assert hashlib.sha256(raw_token.encode("ascii")).hexdigest() == stored_hash
