"""RED -> GREEN, design D40 — `to_amount` derivation precision, rounding,
and the rounds-to-zero guard (tasks.md 1.16, design RED #7/#8/#9).

The pure-`Decimal` unit tests at the top exercise
`app.transfers.service._derive_to_amount` directly, no database (design's
Testing Strategy: "in-memory ... pure Decimal"). The integration tests
below round-trip through the real HTTP/Postgres path to prove the stored
value AND its wire serialization — asserted as `Decimal` AND as the raw
JSON string, never as a float.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.accounts.models import Account
from app.security import issue_access_token
from app.transfers import service


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _account(exchange_rate: str) -> Account:
    return Account(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="unit-test-account",
        currency="USD",
        exchange_rate=Decimal(exchange_rate),
        initial_funds=Decimal(0),
        is_personal=False,
        archived=False,
    )


# --- pure Decimal unit tests, no DB ---


def test_derive_to_amount_exact_conversion_no_rounding_needed() -> None:
    result = service._derive_to_amount(Decimal(100), _account("1"), _account("2"))
    assert result == Decimal("50.00")


def test_derive_to_amount_rounds_half_up_for_a_repeating_decimal() -> None:
    # 100 / 3 = 33.333... -> quantized to 33.33 (truncates below the half).
    result = service._derive_to_amount(Decimal(100), _account("1"), _account("3"))
    assert result == Decimal("33.33")


def test_derive_to_amount_exact_half_rounds_away_from_zero() -> None:
    # 1 * 1 / 8 = 0.125 exactly -> ROUND_HALF_UP rounds the exact half
    # away from zero to 0.13, matching Postgres numeric's own behavior.
    result = service._derive_to_amount(Decimal(1), _account("1"), _account("8"))
    assert result == Decimal("0.13")


def test_derive_to_amount_rounding_to_zero_raises_validation_error() -> None:
    with pytest.raises(service.TransferValidationError):
        service._derive_to_amount(Decimal("0.01"), _account("1"), _account("1000"))


# --- integration: stored value + wire serialization, never a float ---


async def _create_account(client, cookie: str, *, name: str, exchange_rate: str = "1") -> str:
    response = await client.post(
        "/api/accounts",
        json={
            "name": name,
            "currency": "USD",
            "is_personal": False,
            "exchange_rate": exchange_rate,
        },
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_cross_currency_transfer_stores_and_serializes_exact_decimal_string(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="conv-exact@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        from_account = await _create_account(client, cookie, name="From", exchange_rate="1")
        to_account = await _create_account(client, cookie, name="To", exchange_rate="2")

        response = await client.post(
            "/api/transfers",
            json={
                "from_account_id": from_account,
                "to_account_id": to_account,
                "from_amount": "100",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["to_amount"], str)
    assert body["to_amount"] == "50.00"
    assert Decimal(body["to_amount"]) == Decimal("50.00")


async def test_cross_currency_transfer_requiring_rounding_quantizes_half_up(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="conv-rounding@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        from_account = await _create_account(client, cookie, name="From", exchange_rate="1")
        to_account = await _create_account(client, cookie, name="To", exchange_rate="3")

        response = await client.post(
            "/api/transfers",
            json={
                "from_account_id": from_account,
                "to_account_id": to_account,
                "from_amount": "100",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    assert response.json()["to_amount"] == "33.33"


async def test_conversion_rounding_to_zero_is_rejected_with_no_row_persisted(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="conv-zero@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        from_account = await _create_account(client, cookie, name="From", exchange_rate="1")
        to_account = await _create_account(client, cookie, name="To", exchange_rate="1000")

        response = await client.post(
            "/api/transfers",
            json={
                "from_account_id": from_account,
                "to_account_id": to_account,
                "from_amount": "0.01",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )
        listed = await client.get("/api/transfers", cookies={"walleza_access": cookie})

    assert response.status_code == 422
    assert listed.json() == []
