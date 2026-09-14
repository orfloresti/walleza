"""RED -> GREEN, design D83/D84, spec `report-trend`: integration coverage
for the DB-backed bucketed trend query and endpoint — calendar bucketing,
partial-bucket clipping/flagging, zero-bucket densification, invalid-range
and invalid-bucket rejection, and the inherited split/refund/transfer/
currency rules (tasks.md 2.5-2.12).
"""

from __future__ import annotations

import datetime
import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token

TODAY = datetime.datetime.now(tz=datetime.UTC).date()
YESTERDAY = TODAY - datetime.timedelta(days=1)


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _bootstrap_category(
    client: AsyncClient, cookie: str, *, name: str = "Food"
) -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


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


async def _create_transaction(
    client: AsyncClient,
    cookie: str,
    *,
    account_id: str,
    type: str = "expense",
    amount: str,
    occurred_on: str,
    is_refund: bool = False,
    splits: list[dict] | None = None,
) -> dict:
    body = {
        "account_id": account_id,
        "type": type,
        "amount": amount,
        "occurred_on": occurred_on,
        "is_refund": is_refund,
    }
    if splits is not None:
        body["splits"] = splits
    response = await client.post(
        "/api/transactions", json=body, cookies={"walleza_access": cookie}
    )
    assert response.status_code == 201
    return response.json()


async def test_ytd_range_bucketed_by_week_one_entry_per_calendar_week(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="trend-ytd-week@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        year_start = TODAY.replace(month=1, day=1)
        await _create_transaction(
            client, cookie, account_id=account_id, amount="10.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "10.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": year_start.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "week",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "week"
    starts = [p["bucket_start"] for p in body["points"]]
    assert len(starts) == len(set(starts))
    assert body["points"][-1]["total"] != "0"


async def test_range_and_bucket_size_are_independent(seed_user, app_factory) -> None:
    """3-month range + day bucket: never coupled/auto-derived."""
    owner = seed_user(email="trend-independence@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        date_from = TODAY - datetime.timedelta(days=90)

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": date_from.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) == 91


async def test_week_bucket_not_aligned_to_range_start_no_double_count(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="trend-week-unaligned@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        # Range starts on a Wednesday (mid-week).
        wednesday = TODAY - datetime.timedelta(days=(TODAY.weekday() - 2) % 7)
        date_to = wednesday + datetime.timedelta(days=10)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="25.00",
            occurred_on=wednesday.isoformat(),
            splits=[{"category_id": category_id, "amount": "25.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": wednesday.isoformat(),
                "date_to": date_to.isoformat(),
                "currency": "USD",
                "bucket": "week",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert points[0]["partial"] is True
    total_across_buckets = sum(float(p["total"]) for p in points)
    assert total_across_buckets == 25.00


async def test_inclusive_date_to_boundary_included(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-inclusive-boundary@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="15.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "15.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": (TODAY - datetime.timedelta(days=5)).isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "month",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    last_bucket = [p for p in points if p["bucket_start"] <= TODAY.isoformat() <= p["bucket_end"]]
    assert len(last_bucket) == 1
    assert last_bucket[0]["total"] == "15.00"


async def test_middle_bucket_no_activity_appears_at_zero(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-zero-middle@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        date_from = TODAY - datetime.timedelta(days=2)
        date_to = TODAY
        await _create_transaction(
            client, cookie, account_id=account_id, amount="10.00",
            occurred_on=date_from.isoformat(),
            splits=[{"category_id": category_id, "amount": "10.00"}],
        )
        await _create_transaction(
            client, cookie, account_id=account_id, amount="5.00",
            occurred_on=date_to.isoformat(),
            splits=[{"category_id": category_id, "amount": "5.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 3
    assert points[1]["total"] == "0"


async def test_end_before_start_returns_422(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-invalid-range@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": YESTERDAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_refund_reduces_its_bucket_total(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-refund@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="50.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "50.00"}],
        )
        await _create_transaction(
            client, cookie, account_id=account_id, amount="20.00",
            occurred_on=TODAY.isoformat(), is_refund=True,
            splits=[{"category_id": category_id, "amount": "20.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert points[0]["total"] == "30.00"


async def test_transfer_excluded_from_every_bucket(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-transfer@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_a = await _bootstrap_account(client, cookie, name="A")
        account_b = await _bootstrap_account(client, cookie, name="B")

        transfer = await client.post(
            "/api/transfers",
            json={
                "from_account_id": account_a,
                "to_account_id": account_b,
                "from_amount": "300.00",
                "occurred_on": TODAY.isoformat(),
            },
            cookies={"walleza_access": cookie},
        )
        assert transfer.status_code == 201

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert points[0]["total"] == "0"


async def test_missing_bucket_parameter_returns_422(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-missing-bucket@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_invalid_bucket_value_returns_422(seed_user, app_factory) -> None:
    owner = seed_user(email="trend-invalid-bucket@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "fortnight",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_non_matching_currency_contributes_zero_to_bucket(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="trend-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        eur_account_id = await _bootstrap_account(client, cookie, currency="EUR", name="Euro")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=eur_account_id, amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "100.00"}],
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    points = response.json()["points"]
    assert points[0]["total"] == "0"


async def test_cross_workspace_access_denied(app_factory) -> None:
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": TODAY.isoformat(),
                "currency": "USD",
                "bucket": "day",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 403
