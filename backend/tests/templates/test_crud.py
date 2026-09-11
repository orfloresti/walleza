"""GREEN: basic template CRUD (design's Interfaces/Contracts,
`transaction-templates` capability, tasks.md 1.6-1.11) — create/list/get/
update/delete through the real cookie path, `position` ordering, and the
split-allocation requirement.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_category(client, cookie: str, *, name: str, type: str = "expense") -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": type},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_create_list_get_update_delete_template(seed_user, app_factory) -> None:
    owner = seed_user(email="tpl-crud@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie, name="Checking")

        created = await client.post(
            "/api/templates",
            json={
                "name": "Rent",
                "account_id": account_id,
                "type": "expense",
                "amount": "1200.00",
                "notes": "monthly rent",
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        template_id = created.json()["id"]
        assert created.json()["position"] == 0
        assert Decimal(created.json()["amount"]) == Decimal("1200.00")

        listed = await client.get("/api/templates", cookies={"walleza_access": cookie})
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == template_id

        fetched = await client.get(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie}
        )
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Rent"

        updated = await client.patch(
            f"/api/templates/{template_id}",
            json={"notes": "updated notes", "position": 3},
            cookies={"walleza_access": cookie},
        )
        assert updated.status_code == 200
        assert updated.json()["notes"] == "updated notes"
        assert updated.json()["position"] == 3
        # Untouched fields survive a partial update.
        assert Decimal(updated.json()["amount"]) == Decimal("1200.00")

        deleted = await client.delete(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie}
        )
        assert deleted.status_code == 204

        gone = await client.get(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie}
        )
        assert gone.status_code == 404


async def test_template_list_ordered_by_position(seed_user, app_factory) -> None:
    owner = seed_user(email="tpl-position@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie, name="Checking")

        for name, position in (("Third", 3), ("First", 1), ("Second", 2)):
            response = await client.post(
                "/api/templates",
                json={
                    "name": name,
                    "account_id": account_id,
                    "type": "expense",
                    "amount": "10.00",
                    "position": position,
                },
                cookies={"walleza_access": cookie},
            )
            assert response.status_code == 201

        listed = await client.get("/api/templates", cookies={"walleza_access": cookie})

    assert [row["name"] for row in listed.json()] == ["First", "Second", "Third"]


# --- spec's "Templates Support Optional Split Allocation" requirement ---


async def test_template_with_splits_created_and_updated(seed_user, app_factory) -> None:
    owner = seed_user(email="tpl-splits@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie, name="Checking")
        category_a = await _create_category(client, cookie, name="Rent")
        category_b = await _create_category(client, cookie, name="Utilities")

        created = await client.post(
            "/api/templates",
            json={
                "name": "Rent+Utilities",
                "account_id": account_id,
                "type": "expense",
                "amount": "150.00",
                "splits": [
                    {"category_id": category_a, "amount": "100.00"},
                    {"category_id": category_b, "amount": "50.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        template_id = created.json()["id"]
        assert len(created.json()["splits"]) == 2

        # Splits not summing to amount are rejected.
        bad_update = await client.patch(
            f"/api/templates/{template_id}",
            json={"splits": [{"category_id": category_a, "amount": "10.00"}]},
            cookies={"walleza_access": cookie},
        )
        assert bad_update.status_code == 422

        # A valid whole-set replacement succeeds.
        good_update = await client.patch(
            f"/api/templates/{template_id}",
            json={"splits": [{"category_id": category_a, "amount": "150.00"}]},
            cookies={"walleza_access": cookie},
        )
        assert good_update.status_code == 200
        assert len(good_update.json()["splits"]) == 1
