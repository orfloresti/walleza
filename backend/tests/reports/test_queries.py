"""RED -> GREEN, design D79/D82, spec `report-category-breakdown`:
integration coverage for the DB-backed breakdown query and endpoint —
zero-activity categories, split-safe summing, refund sign, currency
scoping, transfer exclusion, empty date range, and validation/workspace
scoping (tasks.md 1.7-1.16, 1.19).
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
    client: AsyncClient, cookie: str, *, name: str = "Food", parent_id: str | None = None
) -> str:
    body = {"name": name, "type": "expense"}
    if parent_id is not None:
        body["parent_id"] = parent_id
    response = await client.post("/api/categories", json=body, cookies={"walleza_access": cookie})
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


def _range_params(currency: str = "USD") -> dict:
    return {
        "date_from": YESTERDAY.isoformat(),
        "date_to": TODAY.isoformat(),
        "currency": currency,
    }


async def test_parent_with_direct_spend_and_children_rolls_up(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-rollup@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        parent = await _bootstrap_category(client, cookie, name="Parent")
        child1 = await _bootstrap_category(client, cookie, name="Child1", parent_id=parent)
        child2 = await _bootstrap_category(client, cookie, name="Child2", parent_id=parent)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="50.00",
            occurred_on=TODAY.isoformat(), splits=[{"category_id": parent, "amount": "50.00"}],
        )
        await _create_transaction(
            client, cookie, account_id=account_id, amount="30.00",
            occurred_on=TODAY.isoformat(), splits=[{"category_id": child1, "amount": "30.00"}],
        )
        await _create_transaction(
            client, cookie, account_id=account_id, amount="20.00",
            occurred_on=TODAY.isoformat(), splits=[{"category_id": child2, "amount": "20.00"}],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[parent]["own"] == "50.00"
    assert by_id[parent]["total"] == "100.00"
    assert by_id[child1]["own"] == "30.00"
    assert by_id[child1]["total"] == "30.00"


async def test_zero_activity_category_still_appears_at_zero(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-zero@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie, name="Unused")

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_id]["own"] == "0"
    assert by_id[category_id]["total"] == "0"


async def test_empty_date_range_still_returns_every_category(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-empty-range@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        far_past = (TODAY - datetime.timedelta(days=3650)).isoformat()
        response = await client.get(
            "/api/reports/category-breakdown",
            params={
                "date_from": far_past,
                "date_to": far_past,
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    slices = response.json()["slices"]
    assert len(slices) >= 1
    assert any(s["category_id"] == category_id for s in slices)


async def test_two_way_split_contributes_partial_amounts(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-split@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_a = await _bootstrap_category(client, cookie, name="A")
        category_b = await _bootstrap_category(client, cookie, name="B")

        await _create_transaction(
            client, cookie, account_id=account_id, amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[
                {"category_id": category_a, "amount": "60.00"},
                {"category_id": category_b, "amount": "40.00"},
            ],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_a]["own"] == "60.00"
    assert by_id[category_b]["own"] == "40.00"


async def test_refund_reduces_category_total(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-refund@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "100.00"}],
        )
        await _create_transaction(
            client, cookie, account_id=account_id, amount="30.00",
            occurred_on=TODAY.isoformat(), is_refund=True,
            splits=[{"category_id": category_id, "amount": "30.00"}],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_id]["own"] == "70.00"


async def test_transfer_never_appears_in_any_category_total(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-transfer@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_a = await _bootstrap_account(client, cookie, name="A")
        account_b = await _bootstrap_account(client, cookie, name="B")
        category_id = await _bootstrap_category(client, cookie)

        transfer = await client.post(
            "/api/transfers",
            json={
                "from_account_id": account_a,
                "to_account_id": account_b,
                "from_amount": "200.00",
                "occurred_on": TODAY.isoformat(),
            },
            cookies={"walleza_access": cookie},
        )
        assert transfer.status_code == 201

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_id]["total"] == "0"


async def test_non_matching_currency_contributes_zero(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        eur_account_id = await _bootstrap_account(client, cookie, currency="EUR", name="Euro")
        # A USD account must ALSO exist in the workspace: the currency
        # validation (spec's "used by at least one account" rule) rejects
        # any `currency` not matching some visible account before the
        # per-category filter even runs.
        await _bootstrap_account(client, cookie, currency="USD", name="Dollar")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=eur_account_id, amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "100.00"}],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(currency="USD"),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_id]["total"] == "0"


async def test_parents_matching_spend_only_in_other_currency_child_is_zero(
    seed_user, app_factory
) -> None:
    """Design D82: currency filtering happens BEFORE rollup, so a parent
    whose only spend is in a different-currency child shows total=0, not
    a partial/leaked total."""
    owner = seed_user(email="breakdown-currency-parent@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        eur_account_id = await _bootstrap_account(client, cookie, currency="EUR", name="Euro")
        await _bootstrap_account(client, cookie, currency="USD", name="Dollar")
        parent = await _bootstrap_category(client, cookie, name="Parent")
        child = await _bootstrap_category(client, cookie, name="Child", parent_id=parent)

        await _create_transaction(
            client, cookie, account_id=eur_account_id, amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": child, "amount": "100.00"}],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(currency="USD"),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[parent]["total"] == "0"


async def test_missing_required_parameter_returns_422(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-missing-param@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            "/api/reports/category-breakdown",
            params={"date_from": TODAY.isoformat(), "date_to": TODAY.isoformat()},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_invalid_date_range_returns_422(seed_user, app_factory) -> None:
    owner = seed_user(email="breakdown-invalid-range@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            "/api/reports/category-breakdown",
            params={
                "date_from": TODAY.isoformat(),
                "date_to": YESTERDAY.isoformat(),
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_cross_workspace_access_denied(app_factory) -> None:
    app = app_factory()
    transport = ASGITransport(app=app)
    # A caller with no `workspace_member` row at all — never bootstrapped
    # a workspace — is rejected by `require_membership` before any query
    # runs (design D18: 403, not 404, for "not a member of anything").
    cookie = _cookie_for(uuid.uuid4())

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 403


async def test_currency_not_used_by_any_account_returns_422(seed_user, app_factory) -> None:
    """Spec `report-category-breakdown`'s "Validation and Workspace
    Scoping" requirement: `currency` MUST match an ISO-4217 code used by
    at least one account in the workspace, not merely be syntactically
    valid ISO-4217 (design D82). An EUR-only workspace queried with a
    syntactically valid but unused currency (GBP) must be rejected, not
    silently answered with an all-zero breakdown."""
    owner = seed_user(email="breakdown-unused-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await _bootstrap_account(client, cookie, currency="EUR", name="Euro")

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(currency="GBP"),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_currency_matching_real_account_still_works(seed_user, app_factory) -> None:
    """Happy-path regression: a `currency` that matches a real account
    continues to succeed exactly as before the validation was added."""
    owner = seed_user(email="breakdown-currency-happy@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie, currency="USD")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client, cookie, account_id=account_id, amount="42.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "42.00"}],
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params=_range_params(currency="USD"),
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    by_id = {s["category_id"]: s for s in response.json()["slices"]}
    assert by_id[category_id]["own"] == "42.00"
