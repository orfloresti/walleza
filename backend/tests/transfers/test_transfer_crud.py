"""GREEN: transfer CRUD (design's Interfaces/Contracts,
`transfer-management` capability, tasks.md 1.8/1.17/1.18) — the
same-account guard's two independent layers (design D42, RED #5), a
client-supplied `to_amount` being silently ignored (RED #10), list
filters matching either side or a date range (RED #6), the structural
absence of PATCH/PUT (RED #11), and the two regression guards that prove
this phase changes nothing about balances or the transaction feed
(RED #12, #13, #14).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
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


async def _create_transfer(
    client, cookie: str, *, from_account_id: str, to_account_id: str, amount: str = "10.00", **extra
):
    payload = {
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "from_amount": amount,
        "occurred_on": "2026-01-15",
    }
    payload.update(extra)
    return await client.post(
        "/api/transfers", json=payload, cookies={"walleza_access": cookie}
    )


# --- design D42 / RED #5: same-account guard, two independent layers ---


async def test_from_account_id_equal_to_account_id_rejected_by_service(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-xfer-same-account@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie, name="Checking")

        response = await _create_transfer(
            client, cookie, from_account_id=account_id, to_account_id=account_id
        )

    assert response.status_code == 422


async def test_direct_insert_with_same_account_bypassing_service_rejected_by_db_check(
    seed_user, app_factory, db_session
) -> None:
    """The DB backstop half of design D42's two-layer pattern: a direct
    `INSERT` (bypassing `app.transfers.service.create_transfer` entirely)
    is rejected by `ck_transfer_distinct_accounts`, independently of the
    service-level 422 proven above."""
    owner = seed_user(email="crud-xfer-same-account-db@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = workspace.json()["id"]
        account_id = await _create_account(client, cookie, name="Checking")

    violated = False
    try:
        db_session.execute(
            sa.text(
                "INSERT INTO app.transfer "
                "(id, workspace_id, from_account_id, to_account_id, from_amount, "
                "to_amount, occurred_on) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, :account_id, "
                "10.00, 10.00, CURRENT_DATE)"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )
        db_session.commit()
    except sa.exc.IntegrityError:
        violated = True
        db_session.rollback()
    assert violated, "from_account_id == to_account_id must violate ck_transfer_distinct_accounts"


# --- RED #10: client-supplied to_amount is silently ignored ---


async def test_client_supplied_to_amount_is_ignored_and_server_value_persists(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-xfer-to-amount-ignored@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        from_account = await _create_account(client, cookie, name="From")
        to_account = await _create_account(client, cookie, name="To")

        response = await _create_transfer(
            client,
            cookie,
            from_account_id=from_account,
            to_account_id=to_account,
            amount="100.00",
            to_amount="999999.99",
        )

    assert response.status_code == 201
    body = response.json()
    # Both accounts default to exchange_rate=1, so the server-computed
    # to_amount is exactly the from_amount — never the client's 999999.99.
    assert Decimal(body["to_amount"]) == Decimal("100.00")
    assert Decimal(body["to_amount"]) != Decimal("999999.99")


# --- RED #6: filter by account matches either side; date range ---


async def test_filter_by_account_id_matches_either_side_unrelated_and_invisible_return_empty(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="crud-xfer-filter-a@example.com")
    owner_b = seed_user(email="crud-xfer-filter-b@example.com")

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

        account_x = await _create_account(client, cookie_a, name="X")
        account_y = await _create_account(client, cookie_a, name="Y")
        account_unrelated = await _create_account(client, cookie_a, name="Unrelated")
        b_personal_response = await client.post(
            "/api/accounts",
            json={"name": "B Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_b},
        )
        b_personal = b_personal_response.json()["id"]

        created = await _create_transfer(
            client, cookie_a, from_account_id=account_x, to_account_id=account_y
        )
        assert created.status_code == 201

        by_from_side = await client.get(
            f"/api/transfers?account_id={account_x}", cookies={"walleza_access": cookie_a}
        )
        by_to_side = await client.get(
            f"/api/transfers?account_id={account_y}", cookies={"walleza_access": cookie_a}
        )
        by_unrelated = await client.get(
            f"/api/transfers?account_id={account_unrelated}",
            cookies={"walleza_access": cookie_a},
        )
        by_invisible = await client.get(
            f"/api/transfers?account_id={b_personal}", cookies={"walleza_access": cookie_a}
        )

    assert len(by_from_side.json()) == 1
    assert len(by_to_side.json()) == 1
    assert by_from_side.json()[0]["id"] == by_to_side.json()[0]["id"]
    assert by_unrelated.status_code == 200
    assert by_unrelated.json() == []
    assert by_invisible.status_code == 200
    assert by_invisible.json() == []


async def test_filter_by_date_range_returns_only_in_range_transfers(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-xfer-date-range@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_x = await _create_account(client, cookie, name="X")
        account_y = await _create_account(client, cookie, name="Y")

        await _create_transfer(
            client, cookie, from_account_id=account_x, to_account_id=account_y, amount="1.00"
        )

        in_range_response = await client.post(
            "/api/transfers",
            json={
                "from_account_id": account_x,
                "to_account_id": account_y,
                "from_amount": "2.00",
                "occurred_on": "2026-06-15",
            },
            cookies={"walleza_access": cookie},
        )
        assert in_range_response.status_code == 201

        by_range = await client.get(
            "/api/transfers?date_from=2026-06-01&date_to=2026-06-30",
            cookies={"walleza_access": cookie},
        )

    assert len(by_range.json()) == 1
    assert by_range.json()[0]["occurred_on"] == "2026-06-15"


# --- design D43 / RED #11: no PATCH/PUT anywhere ---


async def test_patch_and_put_transfer_return_405(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-xfer-no-patch@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_x = await _create_account(client, cookie, name="X")
        account_y = await _create_account(client, cookie, name="Y")
        created = await _create_transfer(
            client, cookie, from_account_id=account_x, to_account_id=account_y
        )
        transfer_id = created.json()["id"]

        patch_response = await client.patch(
            f"/api/transfers/{transfer_id}",
            json={"notes": "edited"},
            cookies={"walleza_access": cookie},
        )
        put_response = await client.put(
            f"/api/transfers/{transfer_id}",
            json={"notes": "edited"},
            cookies={"walleza_access": cookie},
        )

    assert patch_response.status_code == 405
    assert put_response.status_code == 405


def test_openapi_document_registers_no_patch_or_put_for_transfers() -> None:
    from app.main import create_app

    app = create_app()
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/transfers"):
            continue
        assert "patch" not in methods, f"{path} must not register PATCH"
        assert "put" not in methods, f"{path} must not register PUT"


# --- design D34 / RED #12: no balance/summary change ---


async def test_creating_and_deleting_a_transfer_leaves_summary_and_accounts_unchanged(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="crud-xfer-summary@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_x_resp = await client.post(
            "/api/accounts",
            json={
                "name": "X",
                "currency": "USD",
                "is_personal": False,
                "initial_funds": "500.00",
            },
            cookies={"walleza_access": cookie},
        )
        account_x = account_x_resp.json()["id"]
        account_y_resp = await client.post(
            "/api/accounts",
            json={
                "name": "Y",
                "currency": "USD",
                "is_personal": False,
                "initial_funds": "200.00",
            },
            cookies={"walleza_access": cookie},
        )
        account_y = account_y_resp.json()["id"]

        summary_before = await client.get(
            "/api/workspace/summary", cookies={"walleza_access": cookie}
        )

        created = await _create_transfer(
            client, cookie, from_account_id=account_x, to_account_id=account_y, amount="50.00"
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        summary_after_create = await client.get(
            "/api/workspace/summary", cookies={"walleza_access": cookie}
        )

        delete_response = await client.delete(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie}
        )
        assert delete_response.status_code == 204

        summary_after_delete = await client.get(
            "/api/workspace/summary", cookies={"walleza_access": cookie}
        )
        account_x_after = await client.get(
            f"/api/accounts/{account_x}", cookies={"walleza_access": cookie}
        )
        account_y_after = await client.get(
            f"/api/accounts/{account_y}", cookies={"walleza_access": cookie}
        )

    assert summary_before.json() == summary_after_create.json()
    assert summary_before.json() == summary_after_delete.json()
    assert Decimal(account_x_after.json()["initial_funds"]) == Decimal("500.00")
    assert Decimal(account_y_after.json()["initial_funds"]) == Decimal("200.00")


# --- design T7 / RED #13: never merged into the transaction feed ---


async def test_transfer_never_appears_in_the_transaction_feed(seed_user, app_factory) -> None:
    owner = seed_user(email="crud-xfer-not-in-feed@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_x = await _create_account(client, cookie, name="X")
        account_y = await _create_account(client, cookie, name="Y")

        created = await _create_transfer(
            client, cookie, from_account_id=account_x, to_account_id=account_y
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        unfiltered = await client.get(
            "/api/transactions", cookies={"walleza_access": cookie}
        )
        filtered_by_from = await client.get(
            f"/api/transactions?account_id={account_x}", cookies={"walleza_access": cookie}
        )
        filtered_by_to = await client.get(
            f"/api/transactions?account_id={account_y}", cookies={"walleza_access": cookie}
        )

    unfiltered_ids = {row["id"] for row in unfiltered.json()}
    assert transfer_id not in unfiltered_ids
    assert unfiltered.json() == []
    assert filtered_by_from.json() == []
    assert filtered_by_to.json() == []


# --- design T1/T6 / RED #14: deletion is a single-row operation ---


async def test_deleting_a_transfer_removes_exactly_one_row_and_nothing_else(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="crud-xfer-single-row-delete@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_x = await _create_account(client, cookie, name="X")
        account_y = await _create_account(client, cookie, name="Y")

        category = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        assert category.status_code == 201

        transaction = await client.post(
            "/api/transactions",
            json={
                "account_id": account_x,
                "type": "expense",
                "amount": "5.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )
        assert transaction.status_code == 201

        created = await _create_transfer(
            client, cookie, from_account_id=account_x, to_account_id=account_y
        )
        assert created.status_code == 201
        transfer_id = created.json()["id"]

        def _counts():
            return {
                "account": db_session.execute(
                    sa.text("SELECT count(*) FROM app.account")
                ).scalar_one(),
                "transaction": db_session.execute(
                    sa.text("SELECT count(*) FROM app.transaction")
                ).scalar_one(),
                "transaction_category_split": db_session.execute(
                    sa.text("SELECT count(*) FROM app.transaction_category_split")
                ).scalar_one(),
                "category": db_session.execute(
                    sa.text("SELECT count(*) FROM app.category")
                ).scalar_one(),
                "transfer": db_session.execute(
                    sa.text("SELECT count(*) FROM app.transfer")
                ).scalar_one(),
            }

        before = _counts()

        delete_response = await client.delete(
            f"/api/transfers/{transfer_id}", cookies={"walleza_access": cookie}
        )
        assert delete_response.status_code == 204

        after = _counts()

    assert after["transfer"] == before["transfer"] - 1
    assert after["account"] == before["account"]
    assert after["transaction"] == before["transaction"]
    assert after["transaction_category_split"] == before["transaction_category_split"]
    assert after["category"] == before["category"]
