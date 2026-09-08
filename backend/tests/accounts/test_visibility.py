"""RED -> GREEN, design D15/D18, spec RED #2/#12 (tasks.md 5.1/5.4):

- Member A's personal account is invisible to member B (same workspace)
  through EVERY account read path (list, direct-id GET/PATCH/DELETE) —
  404, never 403 (D18: a 403 would confirm the row exists, which is the
  leak).
- A departed member's personal account is invisible to remaining members
  yet the row itself is still SELECTable by id directly against the
  database (retained, never deleted — decision 4).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _join_same_workspace(client, owner_cookie: str, joiner_cookie: str) -> str:
    """Puts `owner` and `joiner` into the SAME workspace via the real
    invite flow (design D12/D20) — not a raw-SQL shortcut — so these tests
    exercise the actual membership boundary account visibility depends on.
    Returns the shared workspace id (the owner's own workspace; the
    joiner's own solo workspace is discarded by `accept_invite`, D20)."""
    owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
    await client.get("/api/workspace", cookies={"walleza_access": joiner_cookie})

    invite = await client.post("/api/workspace/invites", cookies={"walleza_access": owner_cookie})
    assert invite.status_code == 201
    token = _token_from_url(invite.json()["url"])

    accept = await client.post(
        "/api/workspace/invites/accept",
        json={"token": token},
        cookies={"walleza_access": joiner_cookie},
    )
    assert accept.status_code == 204
    return owner_ws.json()["id"]


async def test_member_cannot_access_another_members_personal_account_by_id(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-visibility@example.com")
    owner_b = seed_user(email="b-visibility@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        created = await client.post(
            "/api/accounts",
            json={"name": "A's stash", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_a},
        )
        assert created.status_code == 201
        account_id = created.json()["id"]

        get_response = await client.get(
            f"/api/accounts/{account_id}", cookies={"walleza_access": cookie_b}
        )
        patch_response = await client.patch(
            f"/api/accounts/{account_id}",
            json={"name": "renamed"},
            cookies={"walleza_access": cookie_b},
        )
        delete_response = await client.delete(
            f"/api/accounts/{account_id}", cookies={"walleza_access": cookie_b}
        )

        # The owner's OWN view must still work — proves the 404s above are
        # a visibility boundary, not a broken route.
        owner_view = await client.get(
            f"/api/accounts/{account_id}", cookies={"walleza_access": cookie_a}
        )

    assert get_response.status_code == 404
    assert "A's stash" not in get_response.text
    assert patch_response.status_code == 404
    assert "A's stash" not in patch_response.text
    # DELETE /api/accounts/{id} is not exposed at all in Phase 1 (design's
    # Interfaces table: "Not exposed in Phase 1 — archival replaces
    # deletion"). FastAPI's own routing correctly answers 405 (method not
    # allowed on an existing path) before any handler runs; either way, no
    # data is exposed and nothing is deleted. Asserting the closed set
    # {404, 405} instead of a single value documents that this ambiguity is
    # expected and non-leaking either way.
    assert delete_response.status_code in (404, 405)
    assert "A's stash" not in delete_response.text

    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == "A's stash"


async def test_member_b_does_not_see_member_as_personal_account_in_list(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-list@example.com")
    owner_b = seed_user(email="b-list@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        await client.post(
            "/api/accounts",
            json={"name": "A Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_a},
        )
        await client.post(
            "/api/accounts",
            json={"name": "Shared One", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_a},
        )

        list_as_b = await client.get("/api/accounts", cookies={"walleza_access": cookie_b})
        list_as_a = await client.get("/api/accounts", cookies={"walleza_access": cookie_a})

    names_b = {row["name"] for row in list_as_b.json()}
    names_a = {row["name"] for row in list_as_a.json()}
    assert names_b == {"Shared One"}
    assert names_a == {"A Personal", "Shared One"}


async def test_departed_members_personal_account_invisible_yet_retained_in_db(
    seed_user, app_factory, accounts_db_sessionmaker
) -> None:
    owner_a = seed_user(email="a-departed@example.com")
    owner_b = seed_user(email="b-departed@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        created = await client.post(
            "/api/accounts",
            json={"name": "A's departing stash", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_a},
        )
        account_id = created.json()["id"]

        # A leaves the workspace (self-removal) — their personal account
        # row is retained (decision 4 / design D15), just unreachable.
        leave_response = await client.delete(
            f"/api/workspace/members/{owner_a}", cookies={"walleza_access": cookie_a}
        )
        assert leave_response.status_code == 204

        list_as_b = await client.get("/api/accounts", cookies={"walleza_access": cookie_b})
        get_as_b = await client.get(
            f"/api/accounts/{account_id}", cookies={"walleza_access": cookie_b}
        )

    assert all(row["name"] != "A's departing stash" for row in list_as_b.json())
    assert get_as_b.status_code == 404

    with accounts_db_sessionmaker() as session:
        row = session.execute(
            sa.text("SELECT name FROM app.account WHERE id = :id"), {"id": account_id}
        ).first()
    assert row is not None, "departed member's personal account row must be RETAINED, not deleted"
    assert row.name == "A's departing stash"
