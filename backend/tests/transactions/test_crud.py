"""GREEN: manual transaction CRUD (design's Interfaces/Contracts,
`transaction-management` capability, tasks.md 3.6-3.9) — round-tripping
amount/account/date/notes/is_refund/checked, list filters (account,
category, date range, type), and PR3's explicit scope boundary: a
transaction with ZERO split lines is legal ("uncategorized", design D21) —
PR3 ships no split-write endpoint at all (PR3b's job), so every
transaction created here through the API has zero splits, and the
`category_id` filter is proven against a split row seeded directly via
raw SQL (mirroring `tests/categories/test_deletion.py`'s precedent for
exercising a not-yet-writable table through the real schema PR1 already
migrated).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_create_income_transaction_round_trips_amount_as_json_string(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-income@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        response = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "income",
                "amount": "1234.56",
                "occurred_on": "2026-02-01",
                "notes": "salary",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["amount"], str)
    assert Decimal(body["amount"]) == Decimal("1234.56")
    assert body["type"] == "income"
    assert body["account_id"] == account_id
    assert body["notes"] == "salary"
    assert body["is_refund"] is False
    assert body["checked"] is False
    assert body["occurred_on"] == "2026-02-01"


async def test_create_expense_with_refund_and_checked_flags_persists_exactly(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-expense@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "50.00",
                "occurred_on": "2026-02-02",
                "is_refund": True,
                "checked": True,
            },
            cookies={"walleza_access": cookie},
        )
        transaction_id = created.json()["id"]

        fetched = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert created.status_code == 201
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["is_refund"] is True
    assert body["checked"] is True
    assert body["type"] == "expense"


async def test_update_transaction_fields(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-update@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "20.00",
                "occurred_on": "2026-02-03",
            },
            cookies={"walleza_access": cookie},
        )
        transaction_id = created.json()["id"]

        updated = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"notes": "corrected", "checked": True, "amount": "25.00"},
            cookies={"walleza_access": cookie},
        )

    assert updated.status_code == 200
    body = updated.json()
    assert body["notes"] == "corrected"
    assert body["checked"] is True
    assert Decimal(body["amount"]) == Decimal("25.00")


async def test_delete_transaction_then_404_on_subsequent_fetch(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-delete@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "20.00",
                "occurred_on": "2026-02-03",
            },
            cookies={"walleza_access": cookie},
        )
        transaction_id = created.json()["id"]

        delete_response = await client.delete(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )
        fetch_after_delete = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert fetch_after_delete.status_code == 404


async def test_get_nonexistent_transaction_returns_404(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-notfound@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.get(
            f"/api/transactions/{uuid.uuid4()}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 404


async def test_list_filters_by_account_date_range_and_type(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-filters@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        account_1 = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_1_id = account_1.json()["id"]
        account_2 = await client.post(
            "/api/accounts",
            json={"name": "Savings", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_2_id = account_2.json()["id"]

        await client.post(
            "/api/transactions",
            json={
                "account_id": account_1_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-01-05",
                "notes": "jan expense account 1",
            },
            cookies={"walleza_access": cookie},
        )
        await client.post(
            "/api/transactions",
            json={
                "account_id": account_1_id,
                "type": "income",
                "amount": "500.00",
                "occurred_on": "2026-02-05",
                "notes": "feb income account 1",
            },
            cookies={"walleza_access": cookie},
        )
        await client.post(
            "/api/transactions",
            json={
                "account_id": account_2_id,
                "type": "expense",
                "amount": "30.00",
                "occurred_on": "2026-01-10",
                "notes": "jan expense account 2",
            },
            cookies={"walleza_access": cookie},
        )

        by_account = await client.get(
            f"/api/transactions?account_id={account_1_id}",
            cookies={"walleza_access": cookie},
        )
        by_date_range = await client.get(
            "/api/transactions?date_from=2026-01-01&date_to=2026-01-31",
            cookies={"walleza_access": cookie},
        )
        by_type = await client.get(
            "/api/transactions?type=income", cookies={"walleza_access": cookie}
        )
        by_account_and_date = await client.get(
            f"/api/transactions?account_id={account_1_id}"
            "&date_from=2026-01-01&date_to=2026-01-31",
            cookies={"walleza_access": cookie},
        )

    assert {row["notes"] for row in by_account.json()} == {
        "jan expense account 1",
        "feb income account 1",
    }
    assert {row["notes"] for row in by_date_range.json()} == {
        "jan expense account 1",
        "jan expense account 2",
    }
    assert {row["notes"] for row in by_type.json()} == {"feb income account 1"}
    assert {row["notes"] for row in by_account_and_date.json()} == {"jan expense account 1"}


async def test_uncategorized_transaction_is_legal_and_appears_in_the_unfiltered_list(
    seed_user, app_factory
) -> None:
    """Design D21: zero split lines is a legal state ("uncategorized").
    A plain create with no `splits` field in the request body at all
    succeeds, has an EMPTY `splits` list in the response (PR3b: `splits`
    is always present as a whole-set snapshot, empty means uncategorized
    — no separate `category_id` field ever existed on a transaction), and
    appears in the unfiltered feed."""
    owner = seed_user(email="crud-uncategorized@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        uncategorized = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "15.00",
                "occurred_on": "2026-03-01",
                "notes": "uncategorized expense",
            },
            cookies={"walleza_access": cookie},
        )
        assert uncategorized.status_code == 201
        assert "category_id" not in uncategorized.json()
        assert uncategorized.json()["splits"] == []

        listed = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    assert any(row["notes"] == "uncategorized expense" for row in listed.json())


async def test_category_filter_and_unfiltered_list_do_not_duplicate_a_multi_split_transaction(
    seed_user, app_factory
) -> None:
    """Regression test for design D30's own stated rationale for choosing
    `EXISTS` over `JOIN` in `visible_transactions`'s category filter (\"a
    JOIN over splits changes row cardinality... a multi-split transaction
    double-counts\"). Flagged as a coverage gap in PR3's verify report
    (WARNING #1) and explicitly recommended to land in PR3b, now that
    `POST /api/transactions` accepts inline `splits` (PR3b) instead of
    needing a raw-SQL seed. A transaction split across TWO different
    categories must appear EXACTLY ONCE when filtered by EITHER category,
    and EXACTLY ONCE in the unfiltered list — never duplicated."""
    owner = seed_user(email="crud-cardinality@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        category_a = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        category_a_id = category_a.json()["id"]
        category_b = await client.post(
            "/api/categories",
            json={"name": "Transport", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        category_b_id = category_b.json()["id"]

        multi_split = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
                "occurred_on": "2026-03-10",
                "notes": "multi-split expense",
                "splits": [
                    {"category_id": category_a_id, "amount": "60.00"},
                    {"category_id": category_b_id, "amount": "40.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )
        assert multi_split.status_code == 201
        multi_split_id = multi_split.json()["id"]

        sibling = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "5.00",
                "occurred_on": "2026-03-11",
                "notes": "unrelated sibling expense",
            },
            cookies={"walleza_access": cookie},
        )
        assert sibling.status_code == 201

        filtered_by_a = await client.get(
            f"/api/transactions?category_id={category_a_id}",
            cookies={"walleza_access": cookie},
        )
        filtered_by_b = await client.get(
            f"/api/transactions?category_id={category_b_id}",
            cookies={"walleza_access": cookie},
        )
        unfiltered = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    filtered_by_a_ids = [row["id"] for row in filtered_by_a.json()]
    filtered_by_b_ids = [row["id"] for row in filtered_by_b.json()]
    unfiltered_ids = [row["id"] for row in unfiltered.json()]

    assert filtered_by_a_ids == [multi_split_id], (
        "filtering by category A must return the multi-split transaction exactly once"
    )
    assert filtered_by_b_ids == [multi_split_id], (
        "filtering by category B must return the SAME multi-split transaction exactly once"
    )
    assert unfiltered_ids.count(multi_split_id) == 1, (
        "the unfiltered list must never duplicate a multi-split transaction"
    )
    assert len(unfiltered_ids) == len(set(unfiltered_ids)), (
        "the unfiltered list must contain no duplicate transaction ids at all"
    )


async def test_category_id_filter_matches_only_transactions_with_a_split_referencing_it(
    seed_user, app_factory, db_session
) -> None:
    """Design D30's `EXISTS` category filter, proven end-to-end: a split
    row is seeded directly via raw SQL against the real Postgres (PR3
    ships no split-write endpoint — that is PR3b's job), then the list
    endpoint's `?category_id=` filter is asserted to include only the
    transaction that split references, never the sibling uncategorized
    transaction."""
    owner = seed_user(email="crud-category-filter@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = workspace.json()["id"]

        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        categorized = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "40.00",
                "occurred_on": "2026-03-05",
                "notes": "categorized expense",
            },
            cookies={"walleza_access": cookie},
        )
        categorized_id = categorized.json()["id"]

        uncategorized = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "5.00",
                "occurred_on": "2026-03-06",
                "notes": "still uncategorized",
            },
            cookies={"walleza_access": cookie},
        )
        assert uncategorized.status_code == 201

        category_row = db_session.execute(
            sa.text(
                "INSERT INTO app.category (id, workspace_id, name, type) "
                "VALUES (gen_random_uuid(), :workspace_id, 'Groceries', 'expense') "
                "RETURNING id"
            ),
            {"workspace_id": workspace_id},
        ).first()
        db_session.execute(
            sa.text(
                "INSERT INTO app.transaction_category_split "
                "(id, transaction_id, category_id, amount) "
                "VALUES (gen_random_uuid(), :txn_id, :category_id, 40.00)"
            ),
            {"txn_id": categorized_id, "category_id": category_row.id},
        )
        db_session.commit()

        filtered = await client.get(
            f"/api/transactions?category_id={category_row.id}",
            cookies={"walleza_access": cookie},
        )

    assert filtered.status_code == 200
    assert {row["notes"] for row in filtered.json()} == {"categorized expense"}
