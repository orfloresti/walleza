"""RED -> GREEN, design D38 (the double-aliased `visible_transfers` JOIN)
and D42's account-reference half — spec's "Both Accounts Must Resolve
Inside the Caller's Own Visible Accounts" and "Workspace-Scoped Access
Control" requirements (tasks.md 1.2-1.7, design RED #1-#4).

Every scenario here proves the SAME structural property from a different
angle: `from_account_id` and `to_account_id` must EACH independently
resolve inside the caller's own `visible_accounts(scope)` — an account
from another workspace, or another member's personal account in the same
workspace, is rejected identically to a nonexistent account, on EITHER
side, independently.
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
    invite flow (mirrors `tests/transactions/test_transaction_visibility.
    py`'s helper exactly) — not a raw-SQL shortcut."""
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


async def _create_shared_account(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_transfer(
    client, cookie: str, *, from_account_id: str, to_account_id: str, amount: str = "10.00"
):
    return await client.post(
        "/api/transfers",
        json={
            "from_account_id": from_account_id,
            "to_account_id": to_account_id,
            "from_amount": amount,
            "occurred_on": "2026-01-15",
        },
        cookies={"walleza_access": cookie},
    )


# --- design RED #1: from_account_id / to_account_id independently checked ---


async def test_from_account_id_naming_another_members_personal_account_is_rejected(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-xfer-from@example.com")
    owner_b = seed_user(email="b-xfer-from@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        b_personal = await _create_personal_account(client, cookie_b, name="B Personal")
        a_valid_to = await _create_shared_account(client, cookie_a, name="Shared")

        response = await _create_transfer(
            client, cookie_a, from_account_id=b_personal, to_account_id=a_valid_to
        )

    assert response.status_code == 422
    assert "B Personal" not in response.text


async def test_to_account_id_naming_another_members_personal_account_is_rejected(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-xfer-to@example.com")
    owner_b = seed_user(email="b-xfer-to@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        a_valid_from = await _create_shared_account(client, cookie_a, name="Shared")
        b_personal = await _create_personal_account(client, cookie_b, name="B Personal")

        response = await _create_transfer(
            client, cookie_a, from_account_id=a_valid_from, to_account_id=b_personal
        )

    assert response.status_code == 422
    assert "B Personal" not in response.text


# --- design RED #2: cross-workspace reference, no existence oracle ---


async def test_cross_workspace_account_reference_rejected_same_as_nonexistent(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-xfer-cross@example.com")
    owner_w2 = seed_user(email="w2-xfer-cross@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        w1_account = await _create_shared_account(client, cookie_w1, name="W1 account")
        w2_account = await _create_shared_account(client, cookie_w2, name="W2 account")

        with_foreign_to = await _create_transfer(
            client, cookie_w1, from_account_id=w1_account, to_account_id=w2_account
        )
        random_id = uuid.uuid4()
        with_random_to = await _create_transfer(
            client, cookie_w1, from_account_id=w1_account, to_account_id=str(random_id)
        )

    assert with_foreign_to.status_code == 422
    assert "W2 account" not in with_foreign_to.text
    assert with_random_to.status_code == 422
    # Same status and same error shape as a random nonexistent uuid4 — no
    # existence oracle: a caller cannot distinguish "belongs to another
    # workspace" from "never existed" by response alone.
    assert with_foreign_to.status_code == with_random_to.status_code
    assert with_foreign_to.json().keys() == with_random_to.json().keys()


# --- design RED #3: the double-alias test ---


async def test_transfer_invisible_on_to_side_is_absent_from_list_and_404s_on_get_and_delete(
    seed_user, app_factory
) -> None:
    """A transfer whose `to_account_id` is B's personal account is fully
    valid for B (its creator) but must be structurally invisible to A on
    EVERY verb — the double INNER JOIN in `visible_transfers` means A's
    query never resolves the `to_account_id` side, so the whole row
    disappears for A, not just that one field."""
    owner_a = seed_user(email="a-xfer-alias-to@example.com")
    owner_b = seed_user(email="b-xfer-alias-to@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        shared = await _create_shared_account(client, cookie_a, name="Shared")
        b_personal = await _create_personal_account(client, cookie_b, name="B Personal")

        created = await _create_transfer(
            client, cookie_b, from_account_id=shared, to_account_id=b_personal
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        list_as_a = await client.get("/api/transfers", cookies={"walleza_access": cookie_a})
        get_as_a = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_a}
        )
        delete_as_a = await client.delete(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_a}
        )
        # B's own view must still work — proves the above is a visibility
        # boundary, not a broken route.
        get_as_b = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_b}
        )

    assert transfer_id not in {row["id"] for row in list_as_a.json()}
    assert get_as_a.status_code == 404
    assert delete_as_a.status_code == 404
    assert get_as_b.status_code == 200


async def test_transfer_invisible_on_from_side_is_absent_from_list_and_404s_on_get_and_delete(
    seed_user, app_factory
) -> None:
    """The mirror case: the invisible account is `from_account_id` this
    time, proving the SECOND alias (not just the first) is genuinely an
    independent INNER JOIN."""
    owner_a = seed_user(email="a-xfer-alias-from@example.com")
    owner_b = seed_user(email="b-xfer-alias-from@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        b_personal = await _create_personal_account(client, cookie_b, name="B Personal")
        shared = await _create_shared_account(client, cookie_a, name="Shared")

        created = await _create_transfer(
            client, cookie_b, from_account_id=b_personal, to_account_id=shared
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        list_as_a = await client.get("/api/transfers", cookies={"walleza_access": cookie_a})
        get_as_a = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_a}
        )
        delete_as_a = await client.delete(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_a}
        )
        get_as_b = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_b}
        )

    assert transfer_id not in {row["id"] for row in list_as_a.json()}
    assert get_as_a.status_code == 404
    assert delete_as_a.status_code == 404
    assert get_as_b.status_code == 200


# --- design RED #4: shared + own-personal allowed, both directions ---


async def test_shared_and_own_personal_account_transfer_allowed_both_directions(
    seed_user, app_factory
) -> None:
    """Guards against an over-broad "no personal accounts at all" misreading
    of the double-JOIN: a transfer between a workspace-shared account and
    the CALLER's OWN personal account must succeed in either direction,
    because both accounts individually satisfy `visible_accounts(scope)`
    for that caller."""
    owner_a = seed_user(email="a-xfer-shared-personal@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_a})

        shared = await _create_shared_account(client, cookie_a, name="Shared")
        personal = await _create_personal_account(client, cookie_a, name="A Personal")

        shared_to_personal = await _create_transfer(
            client, cookie_a, from_account_id=shared, to_account_id=personal
        )
        personal_to_shared = await _create_transfer(
            client, cookie_a, from_account_id=personal, to_account_id=shared
        )

    assert shared_to_personal.status_code == 201
    assert personal_to_shared.status_code == 201


# --- spec's explicit reject case: two different members' personal accounts ---


async def test_transfer_between_two_different_members_personal_accounts_is_rejected(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-xfer-two-personal@example.com")
    owner_b = seed_user(email="b-xfer-two-personal@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)

        a_personal = await _create_personal_account(client, cookie_a, name="A Personal")
        b_personal = await _create_personal_account(client, cookie_b, name="B Personal")

        by_a = await _create_transfer(
            client, cookie_a, from_account_id=a_personal, to_account_id=b_personal
        )
        by_b = await _create_transfer(
            client, cookie_b, from_account_id=b_personal, to_account_id=a_personal
        )

    assert by_a.status_code == 422
    assert by_b.status_code == 422


# --- Workspace-Scoped Access Control: non-member of the workspace ---


async def test_non_member_cannot_fetch_list_or_delete_another_workspaces_transfer(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-xfer-owner@example.com")
    non_member = seed_user(email="outsider-xfer@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_outsider = _cookie_for(non_member)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_outsider})

        account_1 = await _create_shared_account(client, cookie_w1, name="W1 Checking")
        account_2 = await _create_shared_account(client, cookie_w1, name="W1 Savings")
        created = await _create_transfer(
            client, cookie_w1, from_account_id=account_1, to_account_id=account_2
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        get_response = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_outsider}
        )
        list_response = await client.get(
            "/api/transfers", cookies={"walleza_access": cookie_outsider}
        )
        delete_response = await client.delete(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_outsider}
        )
        # The row must be left untouched — the owner can still fetch it.
        owner_view = await client.get(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie_w1}
        )

    assert get_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == []
    assert delete_response.status_code == 404
    assert owner_view.status_code == 200
