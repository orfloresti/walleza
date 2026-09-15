"""Design D120/D121, tasks.md Unit 2: proves the OCR draft-exclusion
predicate added to `visible_transactions` actually propagates to every
consumer that builds on it, and that the `DELETE /api/transactions/{id}`
fix (D131's caveat — it must ship in the same commit) still resolves a
draft row for discarding after that exclusion lands.

Drafts are seeded directly via raw SQL (`ocr_status` set) since the
draft-creation endpoint (`POST /api/transactions/draft-from-photo`) is
Unit 3's job, not this unit's — exactly the same "seed a not-yet-writable
shape through the real schema" precedent `test_crud.py`'s docstring
already documents for split rows.
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _seed_draft_transaction(
    db_session,
    *,
    workspace_id,
    account_id,
    ocr_status: str,
    notes: str,
) -> uuid.UUID:
    """Inserts a transaction row directly with a non-NULL, non-confirmed
    `ocr_status` — exactly the shape D120's predicate must exclude."""
    transaction_id = uuid.uuid4()
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction "
            "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
            " is_refund, checked, created_at, updated_at, ocr_status) "
            "VALUES (:id, :ws, :acc, 'expense', 0.01, current_date, :notes, "
            " false, false, now(), now(), :ocr_status)"
        ),
        {
            "id": transaction_id,
            "ws": workspace_id,
            "acc": account_id,
            "notes": notes,
            "ocr_status": ocr_status,
        },
    )
    db_session.commit()
    return transaction_id


async def _setup_workspace_account_category(client, cookie: str):
    ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
    workspace_id = ws.json()["id"]
    account = await client.post(
        "/api/accounts",
        json={"name": "Checking", "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    account_id = account.json()["id"]
    category = await client.post(
        "/api/categories",
        json={"name": "Groceries", "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    category_id = category.json()["id"]
    return workspace_id, account_id, category_id


async def _create_confirmed_transaction(
    client,
    cookie: str,
    *,
    account_id: str,
    category_id: str,
    amount: str,
    notes: str,
    occurred_on: str = "2026-03-10",
) -> str:
    response = await client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": amount,
            "occurred_on": occurred_on,
            "notes": notes,
            "splits": [{"category_id": category_id, "amount": amount}],
        },
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_draft_excluded_from_list_and_confirmed_or_null_appear_normally(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="containment-list@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        ordinary_id = await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="20.00", notes="ordinary NULL row",
        )
        for status in ("pending_ocr", "extracted", "extraction_failed"):
            _seed_draft_transaction(
                db_session, workspace_id=workspace_id, account_id=account_id,
                ocr_status=status, notes=f"draft {status}",
            )

        listed = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    notes = {row["notes"] for row in listed.json()}
    assert notes == {"ordinary NULL row"}
    ids = {row["id"] for row in listed.json()}
    assert ordinary_id in ids


async def test_confirmed_ocr_status_transaction_appears_normally(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="containment-confirmed@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, _category_id = await _setup_workspace_account_category(
            client, cookie
        )
        confirmed_id = _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="confirmed", notes="confirmed via ocr",
        )

        get_response = await client.get(
            f"/api/transactions/{confirmed_id}", cookies={"walleza_access": cookie}
        )
        listed = await client.get("/api/transactions", cookies={"walleza_access": cookie})

    assert get_response.status_code == 200
    assert get_response.json()["notes"] == "confirmed via ocr"
    assert str(confirmed_id) in {row["id"] for row in listed.json()}


async def test_draft_excluded_from_get_by_id(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="containment-get@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, _category_id = await _setup_workspace_account_category(
            client, cookie
        )
        draft_id = _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="pending_ocr", notes="draft get",
        )

        response = await client.get(
            f"/api/transactions/{draft_id}", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 404


async def test_draft_excluded_from_budget_progress(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="containment-budget@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        import datetime

        today = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
        await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="30.00", notes="counted spend", occurred_on=today,
        )
        budget_response = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": account_id,
                "name": "Groceries budget",
                "amount": "100.00",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )
        assert budget_response.status_code == 201
        budget_id = budget_response.json()["id"]
        spent_before = Decimal(budget_response.json()["progress"]["spent"])

        _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="extracted", notes="draft not counted",
        )

        after_response = await client.get(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": cookie}
        )

    spent_after = Decimal(after_response.json()["progress"]["spent"])
    assert spent_after == spent_before == Decimal("30.00")


async def test_draft_excluded_from_category_breakdown_report(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="containment-breakdown@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="15.00", notes="counted breakdown spend",
        )
        _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="extraction_failed", notes="draft breakdown noise",
        )

        response = await client.get(
            "/api/reports/category-breakdown",
            params={
                "date_from": "2026-03-01", "date_to": "2026-03-31", "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    slice_ = next(s for s in response.json()["slices"] if s["category_id"] == category_id)
    assert Decimal(slice_["own"]) == Decimal("15.00")


async def test_draft_excluded_from_trend_report(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="containment-trend@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="45.00", notes="counted trend spend",
        )
        _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="pending_ocr", notes="draft trend noise",
        )

        response = await client.get(
            "/api/reports/trend",
            params={
                "date_from": "2026-03-01", "date_to": "2026-03-31",
                "currency": "USD", "bucket": "month",
            },
            cookies={"walleza_access": cookie},
        )

    total = sum(Decimal(b["total"]) for b in response.json()["points"])
    assert total == Decimal("45.00")


async def test_draft_excluded_from_default_currency_counts(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="containment-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        eur_account = await client.post(
            "/api/accounts",
            json={"name": "EUR account", "currency": "EUR", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        eur_account_id = eur_account.json()["id"]

        await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="10.00", notes="USD count",
        )
        # Seed 3 drafts on the EUR account: if they were counted, EUR would
        # outrank USD (1 confirmed) in `default_currency_counts`'s ordering.
        for status in ("pending_ocr", "extracted", "extraction_failed"):
            _seed_draft_transaction(
                db_session, workspace_id=workspace_id, account_id=eur_account_id,
                ocr_status=status, notes=f"eur draft {status}",
            )

        response = await client.get(
            "/api/reports/default-currency", cookies={"walleza_access": cookie}
        )

    assert response.json()["currency"] == "USD"


async def test_delete_still_works_on_draft_transaction_after_exclusion(
    seed_user, app_factory, db_session
) -> None:
    """Design D131's caveat: `visible_transactions` can no longer see a
    draft after D120, so `delete_transaction` must resolve it through
    `ocr_draft_transactions` instead — this is the fix that MUST ship in
    the same commit as the exclusion predicate."""
    owner = seed_user(email="containment-delete-draft@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id, account_id, _category_id = await _setup_workspace_account_category(
            client, cookie
        )
        draft_id = _seed_draft_transaction(
            db_session, workspace_id=workspace_id, account_id=account_id,
            ocr_status="pending_ocr", notes="abandoned draft",
        )

        delete_response = await client.delete(
            f"/api/transactions/{draft_id}", cookies={"walleza_access": cookie}
        )
        row = db_session.execute(
            sa.text("SELECT count(*) FROM app.transaction WHERE id = :id"),
            {"id": draft_id},
        ).scalar_one()

    assert delete_response.status_code == 204
    assert row == 0


async def test_delete_still_works_normally_on_ordinary_transaction(
    seed_user, app_factory
) -> None:
    """No regression: an ordinary (NULL `ocr_status`) transaction still
    deletes via the sanctioned `visible_transactions` path."""
    owner = seed_user(email="containment-delete-ordinary@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        _workspace_id, account_id, category_id = await _setup_workspace_account_category(
            client, cookie
        )
        transaction_id = await _create_confirmed_transaction(
            client, cookie, account_id=account_id, category_id=category_id,
            amount="5.00", notes="ordinary to delete",
        )

        delete_response = await client.delete(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )
        get_after = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert get_after.status_code == 404


def test_ocr_draft_transactions_is_not_imported_outside_the_allowlist() -> None:
    """Structural AST test (D121 #2): only `app/transactions/{queries,
    service,router}.py` and `app/ocr/**` may import `ocr_draft_transactions`
    — everything else must go through `visible_transactions`, the
    sanctioned default that already excludes drafts."""
    allowlist = {
        BACKEND_DIR / "app" / "transactions" / "queries.py",
        BACKEND_DIR / "app" / "transactions" / "service.py",
        BACKEND_DIR / "app" / "transactions" / "router.py",
    }
    app_dir = BACKEND_DIR / "app"
    offenders: list[Path] = []
    for path in app_dir.rglob("*.py"):
        if path in allowlist:
            continue
        if path.parts[len(BACKEND_DIR.parts) :][:2] == ("app", "ocr"):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.names and any(
                alias.name == "ocr_draft_transactions" for alias in node.names
            ):
                offenders.append(path)
    assert offenders == [], f"ocr_draft_transactions imported outside allowlist: {offenders}"


def test_exactly_one_transaction_select_call_site() -> None:
    """Structural AST test (D121 #2): `sa.select(Transaction)` must appear
    in exactly one place in the whole backend — `visible_transactions`
    inside `app/transactions/queries.py` — confirming design's own
    repo-wide-grep claim that this really is the single choke point every
    financial aggregate builds on."""
    app_dir = BACKEND_DIR / "app"
    hits: list[tuple[Path, int]] = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_select_call = (
                isinstance(func, ast.Attribute)
                and func.attr == "select"
                and isinstance(func.value, ast.Name)
                and func.value.id == "sa"
            )
            if not is_select_call:
                continue
            if any(
                isinstance(arg, ast.Name) and arg.id == "Transaction" for arg in node.args
            ):
                hits.append((path, node.lineno))
    # Design D120/D121 #2's exact wording: `sa.select(Transaction)` appears
    # in exactly one FILE. Adding `ocr_draft_transactions` (design's
    # deliberately narrow complement, D120) means there are now two call
    # sites, but both live inside `visible_transactions`/
    # `ocr_draft_transactions` in this same module — no third, competing
    # query path was introduced anywhere else in the backend.
    files_with_hits = {path for path, _lineno in hits}
    assert files_with_hits == {BACKEND_DIR / "app" / "transactions" / "queries.py"}, hits
    assert len(hits) == 2, hits


def test_visible_transactions_has_no_draft_named_parameter() -> None:
    """Structural AST test (D121 #3): `visible_transactions` must carry no
    parameter whose name contains `draft` — the dangerous "see everything"
    behavior is reachable only through the separate, narrowly-named
    `ocr_draft_transactions` helper, never a kwarg on the sanctioned
    default path."""
    import inspect

    from app.transactions import queries

    sig = inspect.signature(queries.visible_transactions)
    assert not any("draft" in name for name in sig.parameters), sig.parameters
