"""RED -> GREEN, design D71-D78, spec `budget-progress`: covers the
current-month SUM, split-transaction attribution, currency/account
scoping, refund/transfer sign handling, status classification wiring, the
list endpoint's single-grouped-query guarantee (D78), and the
month-boundary reset (tasks.md 1b.3-1b.6).
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.budgets.service import (
    current_month_bounds,
    get_budget_progress,
    list_budgets_with_progress,
)
from app.security import issue_access_token

TODAY = datetime.datetime.now(tz=datetime.UTC).date()


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _bootstrap_category(client: AsyncClient, cookie: str, *, name: str = "Food") -> str:
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


async def _create_budget(
    client: AsyncClient,
    cookie: str,
    *,
    category_id: str,
    account_id: str | None = None,
    amount: str = "500.00",
    currency: str = "USD",
) -> dict:
    body: dict = {"category_id": category_id, "amount": amount, "currency": currency}
    if account_id is not None:
        body["account_id"] = account_id
    response = await client.post("/api/budgets", json=body, cookies={"walleza_access": cookie})
    assert response.status_code == 201
    return response.json()


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


async def test_split_transaction_only_counts_own_category_line(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-split@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_a = await _bootstrap_category(client, cookie, name="Groceries")
        category_b = await _bootstrap_category(client, cookie, name="Transport")

        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[
                {"category_id": category_a, "amount": "60.00"},
                {"category_id": category_b, "amount": "40.00"},
            ],
        )

        budget = await _create_budget(client, cookie, category_id=category_a, amount="500.00")
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "60.00"


async def test_no_double_counting_across_two_budgets_on_split_categories(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="progress-nodup@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_a = await _bootstrap_category(client, cookie, name="Groceries")
        category_b = await _bootstrap_category(client, cookie, name="Transport")

        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[
                {"category_id": category_a, "amount": "60.00"},
                {"category_id": category_b, "amount": "40.00"},
            ],
        )

        budget_a = await _create_budget(client, cookie, category_id=category_a, amount="500.00")
        budget_b = await _create_budget(client, cookie, category_id=category_b, amount="500.00")

        response = await client.get("/api/budgets", cookies={"walleza_access": cookie})

    assert response.status_code == 200
    by_id = {b["id"]: b for b in response.json()}
    assert by_id[budget_a["id"]]["progress"]["spent"] == "60.00"
    assert by_id[budget_b["id"]]["progress"]["spent"] == "40.00"


async def test_currency_mismatch_excludes_transactions(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        eur_account_id = await _bootstrap_account(client, cookie, currency="EUR", name="Euro")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client,
            cookie,
            account_id=eur_account_id,
            amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "100.00"}],
        )

        # Category-only budget in USD — the EUR transaction must never
        # count toward it (design D72: WHERE on account currency, no
        # conversion).
        budget = await _create_budget(
            client, cookie, category_id=category_id, amount="500.00", currency="USD"
        )
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "0.00" or response.json()["progress"]["spent"] == "0"


async def test_category_only_budget_aggregates_across_multiple_accounts(
    seed_user, app_factory
) -> None:
    """Design D72: a category-only budget (`account_id=None`) has no
    account predicate at all, so it must aggregate spend across every
    same-currency account in the workspace, not just one."""
    owner = seed_user(email="progress-multi-account@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_a = await _bootstrap_account(client, cookie, currency="USD", name="A")
        account_b = await _bootstrap_account(client, cookie, currency="USD", name="B")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client,
            cookie,
            account_id=account_a,
            amount="50.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "50.00"}],
        )
        await _create_transaction(
            client,
            cookie,
            account_id=account_b,
            amount="30.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "30.00"}],
        )

        budget = await _create_budget(client, cookie, category_id=category_id, amount="500.00")
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "80.00"


async def test_account_scoped_budget_restricts_to_one_account(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-account-scope@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_a = await _bootstrap_account(client, cookie, name="A")
        account_b = await _bootstrap_account(client, cookie, name="B")
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client,
            cookie,
            account_id=account_a,
            amount="50.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "50.00"}],
        )
        await _create_transaction(
            client,
            cookie,
            account_id=account_b,
            amount="30.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "30.00"}],
        )

        budget = await _create_budget(
            client, cookie, category_id=category_id, account_id=account_a, amount="500.00"
        )
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "50.00"


async def test_refund_reduces_spent(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-refund@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="100.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "100.00"}],
        )
        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="30.00",
            occurred_on=TODAY.isoformat(),
            is_refund=True,
            splits=[{"category_id": category_id, "amount": "30.00"}],
        )

        budget = await _create_budget(client, cookie, category_id=category_id, amount="500.00")
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "70.00"


async def test_income_is_ignored(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-income@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie, name="Salary")

        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            type="income",
            amount="1000.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "1000.00"}],
        )

        budget = await _create_budget(client, cookie, category_id=category_id, amount="500.00")
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "0.00" or response.json()["progress"]["spent"] == "0"


async def test_transfer_excluded(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-transfer@example.com")
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

        budget = await _create_budget(
            client, cookie, category_id=category_id, account_id=account_a, amount="500.00"
        )
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    assert response.json()["progress"]["spent"] == "0.00" or response.json()["progress"]["spent"] == "0"


async def test_status_field_reflects_over_budget(seed_user, app_factory) -> None:
    owner = seed_user(email="progress-status@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="600.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "600.00"}],
        )

        budget = await _create_budget(client, cookie, category_id=category_id, amount="500.00")
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 200
    progress = response.json()["progress"]
    assert progress["status"] == "over_budget"
    assert progress["remaining"] == "-100.00"


async def test_list_progress_is_a_single_grouped_query_not_n_plus_1(
    seed_user, app_factory, budgets_db_sessionmaker
) -> None:
    """Design D78: `GET /budgets` must not issue one SUM query per
    budget. Seeds several budgets and asserts the number of SQL
    statements executed to compute their progress stays bounded
    regardless of budget count (one query for the budgets list's
    progress, not N)."""
    owner = seed_user(email="progress-query-count@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    category_ids: list[str] = []
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        for i in range(5):
            category_id = await _bootstrap_category(client, cookie, name=f"Cat{i}")
            category_ids.append(category_id)
            await _create_budget(client, cookie, category_id=category_id, amount="100.00")

    from app.deps import WorkspaceScope

    session = budgets_db_sessionmaker()
    try:
        row = session.execute(
            sa.text("SELECT workspace_id FROM app.workspace_member WHERE user_id = :uid"),
            {"uid": owner},
        ).first()
        workspace_id = row[0]
        scope = WorkspaceScope(workspace_id=workspace_id, user_id=owner)

        statements: list[str] = []

        def _listener(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        engine = session.get_bind()
        sa.event.listen(engine, "before_cursor_execute", _listener)
        try:
            list_budgets_with_progress(session, scope=scope)
        finally:
            sa.event.remove(engine, "before_cursor_execute", _listener)

        # One query to list the budgets, one grouped query for progress —
        # never one-per-budget (5 budgets would mean 7+ statements if
        # N+1'd).
        assert len(statements) <= 2, statements
    finally:
        session.close()


async def test_month_boundary_reset_excludes_prior_month_spend(
    seed_user, app_factory, budgets_db_sessionmaker
) -> None:
    """Design D76/D77: a budget's spend recomputes purely from the
    current calendar month with no stored carry-over. Seeds a
    current-month transaction through the real API/router (so the full
    stack — including `POST /api/transactions`'s split validation — is
    exercised), then pushes that transaction's `occurred_on` into the
    PRIOR month via a direct raw-SQL update and re-reads progress through
    `get_budget_progress` directly, asserting the prior-month spend no
    longer counts and nothing was mutated on the budget/stored total."""
    owner = seed_user(email="progress-month-boundary@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _bootstrap_account(client, cookie)
        category_id = await _bootstrap_category(client, cookie)

        txn = await _create_transaction(
            client,
            cookie,
            account_id=account_id,
            amount="400.00",
            occurred_on=TODAY.isoformat(),
            splits=[{"category_id": category_id, "amount": "400.00"}],
        )
        budget = await _create_budget(client, cookie, category_id=category_id, amount="500.00")

        # Sanity: while still in the current month, the transaction counts.
        response = await client.get(
            f"/api/budgets/{budget['id']}", cookies={"walleza_access": cookie}
        )
        assert response.json()["progress"]["spent"] == "400.00"

    prior_month_date = TODAY.replace(day=1) - datetime.timedelta(days=1)

    from app.deps import WorkspaceScope

    session = budgets_db_sessionmaker()
    try:
        session.execute(
            sa.text("UPDATE app.transaction SET occurred_on = :d WHERE id = :id"),
            {"d": prior_month_date, "id": txn["id"]},
        )
        session.commit()

        row = session.execute(
            sa.text("SELECT workspace_id FROM app.workspace_member WHERE user_id = :uid"),
            {"uid": owner},
        ).first()
        scope = WorkspaceScope(workspace_id=row[0], user_id=owner)

        _, progress = get_budget_progress(
            session, scope=scope, budget_id=uuid.UUID(budget["id"]), today=TODAY
        )

        assert progress.spent == 0
        assert progress.period_start == current_month_bounds(TODAY)[0]
        assert progress.period_end == current_month_bounds(TODAY)[1]
    finally:
        session.rollback()
        session.close()
