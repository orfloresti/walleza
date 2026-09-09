"""RED -> GREEN, spec "Account FK Must Belong to the Requester's Own
Workspace" (tasks.md 3.4): a transaction's `account_id` MUST reference an
account in the requester's own workspace — an account id from another
workspace must not be accepted, even if guessed, on either create or
update. Mirrors `app.categories.service._validate_parent_reference`'s
cross-workspace `parent_id` rejection: reject as if the reference did not
exist, mapped to 422 since `account_id` is a request BODY field, not a
resource fetched by id (D18's 404 stays reserved for that case).
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_creating_a_transaction_with_another_workspaces_account_id_is_rejected(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-cross@example.com")
    owner_w2 = seed_user(email="w2-cross@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        w2_account = await client.post(
            "/api/accounts",
            json={"name": "W2 account", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w2},
        )
        assert w2_account.status_code == 201
        w2_account_id = w2_account.json()["id"]

        create_in_w1 = await client.post(
            "/api/transactions",
            json={
                "account_id": w2_account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie_w1},
        )

    assert create_in_w1.status_code == 422
    assert "W2 account" not in create_in_w1.text


async def test_updating_a_transaction_to_another_workspaces_account_id_is_rejected(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-cross-update@example.com")
    owner_w2 = seed_user(email="w2-cross-update@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        w1_account = await client.post(
            "/api/accounts",
            json={"name": "W1 account", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w1},
        )
        w1_account_id = w1_account.json()["id"]

        w2_account = await client.post(
            "/api/accounts",
            json={"name": "W2 account", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w2},
        )
        w2_account_id = w2_account.json()["id"]

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": w1_account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie_w1},
        )
        assert created.status_code == 201
        transaction_id = created.json()["id"]

        update_response = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"account_id": w2_account_id},
            cookies={"walleza_access": cookie_w1},
        )

        unchanged = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie_w1}
        )

    assert update_response.status_code == 422
    assert unchanged.json()["account_id"] == w1_account_id


async def test_creating_a_transaction_with_another_members_personal_account_id_is_rejected(
    seed_user, app_factory
) -> None:
    """Same-workspace variant: a random guess of another MEMBER's personal
    account id (not merely a foreign workspace) must be rejected exactly
    the same way — `visible_accounts(scope)` excludes it either way."""
    owner_a = seed_user(email="a-cross-personal@example.com")
    owner_b = seed_user(email="b-cross-personal@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        owner_ws = await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_b})
        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": cookie_a}
        )
        token = invite.json()["url"].rsplit("/", 1)[-1]
        accept = await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": cookie_b},
        )
        assert accept.status_code == 204
        assert owner_ws.status_code == 200

        b_personal = await client.post(
            "/api/accounts",
            json={"name": "B Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_b},
        )
        b_personal_id = b_personal.json()["id"]

        create_by_a = await client.post(
            "/api/transactions",
            json={
                "account_id": b_personal_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie_a},
        )

    assert create_by_a.status_code == 422
    assert "B Personal" not in create_by_a.text
