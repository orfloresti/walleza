"""RED -> GREEN, spec "Subscriptions View Is a Filter, Not a Separate
Entity" (tasks.md 1.17): `GET /api/recurring?is_subscription=true` returns
only flagged recurrences; no separate route or resource exists."""

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


async def test_listing_with_is_subscription_filter_returns_only_subscriptions(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="rec-subs-filter@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        subscription = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "9.99",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "is_subscription": True,
            },
            cookies={"walleza_access": cookie},
        )
        assert subscription.status_code == 201
        subscription_id = subscription.json()["id"]

        non_subscription = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "1200.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "is_subscription": False,
            },
            cookies={"walleza_access": cookie},
        )
        assert non_subscription.status_code == 201

        subs_only = await client.get(
            "/api/recurring?is_subscription=true", cookies={"walleza_access": cookie}
        )
        non_subs_only = await client.get(
            "/api/recurring?is_subscription=false", cookies={"walleza_access": cookie}
        )
        unfiltered = await client.get(
            "/api/recurring", cookies={"walleza_access": cookie}
        )

    assert [row["id"] for row in subs_only.json()] == [subscription_id]
    assert all(row["is_subscription"] is True for row in subs_only.json())
    assert all(row["is_subscription"] is False for row in non_subs_only.json())
    assert len(unfiltered.json()) == 2


def test_no_separate_subscriptions_route_registered() -> None:
    from app.main import create_app

    app = create_app()
    schema = app.openapi()
    assert "/api/subscriptions" not in schema["paths"]
