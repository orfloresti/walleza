"""GREEN: basic recurring CRUD (design's Interfaces/Contracts,
`recurring-transactions` capability, tasks.md 1.12-1.18) — create/list/
get/update/delete through the real cookie path, plus the split-allocation
sum invariant mirrored from `app.transactions.service.replace_splits`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str, *, name: str = "Checking") -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_category(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_create_list_get_update_delete_recurring(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-crud@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "1200.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "notes": "monthly rent",
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        recurring_id = created.json()["id"]
        assert created.json()["next_date"] == "2026-01-01"
        assert created.json()["occurrence_index"] == 0
        assert Decimal(created.json()["amount"]) == Decimal("1200.00")

        listed = await client.get("/api/recurring", cookies={"walleza_access": cookie})
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == recurring_id

        fetched = await client.get(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie}
        )
        assert fetched.status_code == 200
        assert fetched.json()["period"] == "month"

        updated = await client.patch(
            f"/api/recurring/{recurring_id}",
            json={"notes": "updated notes"},
            cookies={"walleza_access": cookie},
        )
        assert updated.status_code == 200
        assert updated.json()["notes"] == "updated notes"
        assert Decimal(updated.json()["amount"]) == Decimal("1200.00")

        deleted = await client.delete(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie}
        )
        assert deleted.status_code == 204

        gone = await client.get(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie}
        )
        assert gone.status_code == 404


async def test_recurring_with_splits_created_and_sum_invariant_enforced(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="rec-splits@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="Rent")
        category_b = await _create_category(client, cookie, name="Utilities")

        bad_create = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "150.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "splits": [{"category_id": category_a, "amount": "10.00"}],
            },
            cookies={"walleza_access": cookie},
        )
        assert bad_create.status_code == 422

        created = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "150.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "splits": [
                    {"category_id": category_a, "amount": "100.00"},
                    {"category_id": category_b, "amount": "50.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        assert len(created.json()["splits"]) == 2
