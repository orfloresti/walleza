"""RED -> GREEN, design D86, spec `report-default-currency`: single
majority, deterministic tie-break, and zero-transaction fallback
(tasks.md 1.17).
"""

from __future__ import annotations

import datetime
import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token

TODAY = datetime.datetime.now(tz=datetime.UTC).date()


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _bootstrap_account(
    client: AsyncClient, cookie: str, *, currency: str = "USD", name: str = "Checking"
) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": currency, "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _bootstrap_category(client: AsyncClient, cookie: str, *, name: str = "Cat") -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_transaction(
    client: AsyncClient, cookie: str, *, account_id: str, amount: str, category_id: str
) -> None:
    response = await client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": amount,
            "occurred_on": TODAY.isoformat(),
            "is_refund": False,
            "splits": [{"category_id": category_id, "amount": amount}],
        },
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201


async def test_single_clear_majority(seed_user, app_factory) -> None:
    owner = seed_user(email="default-currency-majority@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        usd_account = await _bootstrap_account(client, cookie, currency="USD", name="USD")
        eur_account = await _bootstrap_account(client, cookie, currency="EUR", name="EUR")
        category_id = await _bootstrap_category(client, cookie)

        for _ in range(4):
            await _create_transaction(
                client, cookie, account_id=usd_account, amount="10.00", category_id=category_id
            )
        await _create_transaction(
            client, cookie, account_id=eur_account, amount="10.00", category_id=category_id
        )

        response = await client.get(
            "/api/reports/default-currency", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["currency"] == "USD"


async def test_tie_break_prefers_earliest_created_account(
    seed_user, app_factory, reports_db_sessionmaker
) -> None:
    """Design D86: two currencies with equal transaction counts tie-break
    to the earliest-created account's currency, deterministically."""
    owner = seed_user(email="default-currency-tie@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        # EUR account created first.
        eur_account = await _bootstrap_account(client, cookie, currency="EUR", name="EUR")
        usd_account = await _bootstrap_account(client, cookie, currency="USD", name="USD")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=eur_account, amount="10.00", category_id=category_id
        )
        await _create_transaction(
            client, cookie, account_id=usd_account, amount="10.00", category_id=category_id
        )

        response = await client.get(
            "/api/reports/default-currency", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["currency"] == "EUR"


async def test_no_transactions_falls_back_to_earliest_account_currency(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="default-currency-no-txn@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await _bootstrap_account(client, cookie, currency="EUR", name="EUR")

        response = await client.get(
            "/api/reports/default-currency", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["currency"] == "EUR"


async def test_no_accounts_returns_none(seed_user, app_factory, reports_db_sessionmaker) -> None:
    """A workspace with zero accounts returns `currency: null` so the
    frontend can prompt for an explicit selection (design D86)."""
    owner = seed_user(email="default-currency-empty@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        response = await client.get(
            "/api/reports/default-currency", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["currency"] is None
