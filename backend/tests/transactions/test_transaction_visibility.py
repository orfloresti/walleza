"""RED -> GREEN, design D30, spec `transaction-visibility` (tasks.md
3.1/3.2):

- A transaction on member B's personal account is invisible to member A
  (same workspace) through EVERY transaction read path (list, direct-id
  GET/PATCH/DELETE) — 404, never 403 (D18: a 403 would confirm the row
  exists, which is the leak).
- Filtering the feed by an `account_id` naming another member's personal
  account returns an EMPTY list, never a 200/404 status discrepancy that
  would let a member probe for the existence of an account they cannot
  see (design RED #2).
- A member of a DIFFERENT workspace entirely gets 404 on a direct-id
  fetch, mirroring `visible_accounts`' workspace-boundary behavior.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _join_same_workspace(client, owner_cookie: str, joiner_cookie: str) -> str:
    """Puts `owner` and `joiner` into the SAME workspace via the real
    invite flow (design D12/D20) — not a raw-SQL shortcut — so these
    tests exercise the actual membership boundary transaction visibility
    depends on. Returns the shared (owner's) workspace id."""
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


async def _create_personal_account(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": True},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_transaction(client, cookie: str, *, account_id: str, notes: str) -> str:
    response = await client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": "42.50",
            "occurred_on": "2026-01-15",
            "notes": notes,
        },
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_member_cannot_access_another_members_personal_account_transaction_by_id(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-txn-visibility@example.com")
    owner_b = seed_user(email="b-txn-visibility@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)
        account_id = await _create_personal_account(client, cookie_a, name="A's stash")
        transaction_id = await _create_transaction(
            client, cookie_a, account_id=account_id, notes="A's secret expense"
        )

        get_response = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie_b}
        )
        patch_response = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"notes": "renamed"},
            cookies={"walleza_access": cookie_b},
        )
        delete_response = await client.delete(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie_b}
        )

        # The owner's OWN view must still work — proves the 404s above are
        # a visibility boundary, not a broken route.
        owner_view = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie_a}
        )

    assert get_response.status_code == 404
    assert "A's secret expense" not in get_response.text
    assert patch_response.status_code == 404
    assert "A's secret expense" not in patch_response.text
    assert delete_response.status_code == 404
    assert "A's secret expense" not in delete_response.text

    assert owner_view.status_code == 200
    assert owner_view.json()["notes"] == "A's secret expense"


async def test_member_b_does_not_see_member_as_personal_account_transaction_in_list(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-txn-list@example.com")
    owner_b = seed_user(email="b-txn-list@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        personal_account_id = await _create_personal_account(client, cookie_a, name="A Personal")
        shared_response = await client.post(
            "/api/accounts",
            json={"name": "Shared One", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_a},
        )
        shared_account_id = shared_response.json()["id"]

        await _create_transaction(
            client, cookie_a, account_id=personal_account_id, notes="A personal expense"
        )
        await _create_transaction(
            client, cookie_a, account_id=shared_account_id, notes="Shared expense"
        )

        list_as_b = await client.get("/api/transactions", cookies={"walleza_access": cookie_b})
        list_as_a = await client.get("/api/transactions", cookies={"walleza_access": cookie_a})

    notes_b = {row["notes"] for row in list_as_b.json()}
    notes_a = {row["notes"] for row in list_as_a.json()}
    assert notes_b == {"Shared expense"}
    assert notes_a == {"A personal expense", "Shared expense"}


async def test_filtering_by_account_id_naming_bs_personal_account_returns_empty_not_404(
    seed_user, app_factory
) -> None:
    """Design RED #2: a member cannot discover another member's personal
    account exists by probing `?account_id=` and observing a 200/404 (or
    populated/empty) discrepancy — the filtered list is just empty, 200,
    same as if the id did not exist at all."""
    owner_a = seed_user(email="a-txn-filter@example.com")
    owner_b = seed_user(email="b-txn-filter@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        b_personal_account_id = await _create_personal_account(client, cookie_b, name="B Personal")
        await _create_transaction(
            client, cookie_b, account_id=b_personal_account_id, notes="B's own expense"
        )

        filtered_by_a = await client.get(
            f"/api/transactions?account_id={b_personal_account_id}",
            cookies={"walleza_access": cookie_a},
        )
        # An account id that plainly does not exist at all must produce the
        # exact SAME shape of response — same status, empty list — so a
        # prober cannot distinguish "exists but hidden" from "never existed".
        random_id = uuid.uuid4()
        filtered_by_random = await client.get(
            f"/api/transactions?account_id={random_id}",
            cookies={"walleza_access": cookie_a},
        )

    assert filtered_by_a.status_code == 200
    assert filtered_by_a.json() == []
    assert filtered_by_random.status_code == 200
    assert filtered_by_random.json() == []


async def test_non_member_of_workspace_cannot_access_transaction_from_another_workspace(
    seed_user, app_factory
) -> None:
    """Two users in entirely SEPARATE workspaces (no shared invite): W2's
    member cannot fetch W1's transaction by id."""
    owner_w1 = seed_user(email="w1-owner@example.com")
    owner_w2 = seed_user(email="w2-owner@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        account_id = await _create_personal_account(client, cookie_w1, name="W1 account")
        transaction_id = await _create_transaction(
            client, cookie_w1, account_id=account_id, notes="W1's expense"
        )

        cross_workspace_get = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie_w2}
        )

    assert cross_workspace_get.status_code == 404
    assert "W1's expense" not in cross_workspace_get.text
