"""RED -> GREEN, spec "Period and Repeat-Every Validation" and
"ends_on Must Not Precede the Start Date" (tasks.md 1.13)."""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": "Checking", "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_invalid_period_value_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-invalid-period@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        response = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "fortnight",
                "starts_on": "2026-01-01",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_non_positive_repeat_every_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-invalid-repeat@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        for bad_value in (0, -1):
            response = await client.post(
                "/api/recurring",
                json={
                    "account_id": account_id,
                    "type": "expense",
                    "amount": "10.00",
                    "repeat_every": bad_value,
                    "period": "month",
                    "starts_on": "2026-01-01",
                },
                cookies={"walleza_access": cookie},
            )
            assert response.status_code == 422


async def test_ends_on_before_start_date_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-ends-before-start@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        response = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-06-01",
                "ends_on": "2026-05-01",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_ends_on_before_start_date_is_rejected_on_update_too(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="rec-ends-before-start-update@example.com")
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
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-06-01",
            },
            cookies={"walleza_access": cookie},
        )
        recurring_id = created.json()["id"]

        response = await client.patch(
            f"/api/recurring/{recurring_id}",
            json={"ends_on": "2026-01-01"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_ends_on_equal_to_start_date_is_accepted(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-ends-equal-start@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        response = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-06-01",
                "ends_on": "2026-06-01",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
