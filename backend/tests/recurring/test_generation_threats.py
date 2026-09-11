"""Threat matrix for `scheduled-occurrence-generation` (design's
re-derived Threat Matrix, cases 1-6, plus D47's concurrency case and
D45/D46's structural-unreachability/import-graph assertions —
tasks.md 2.1-2.8, 2.16). This is the phase's single most
security-critical file: an unauthenticated, cross-workspace-iterating
code path with no request-scoped `WorkspaceScope` at all.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.recurring import generation
from app.security import issue_access_token

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Threat 1: unreachable from the public HTTP surface (design D45)
# ---------------------------------------------------------------------------


def test_no_route_or_openapi_path_reaches_generation() -> None:
    from app.main import create_app

    app = create_app()
    for route in app.routes:
        path = getattr(route, "path", "")
        assert "scheduler" not in path
        assert "generation" not in path
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "") or ""
        assert "scheduler" not in module
        assert "generation" not in module

    schema = app.openapi()
    for path in schema["paths"]:
        assert "scheduler" not in path
        assert "generation" not in path


def test_scheduler_module_importable_without_app_main() -> None:
    """`app.scheduler`/`app.recurring.generation` never import `app.main`,
    Mangum, or anything ASGI-shaped — proven in a fresh subprocess so an
    already-imported `app.main` in THIS test process cannot mask a real
    coupling."""
    script = (
        "import sys; import app.scheduler; "
        "assert 'app.main' not in sys.modules, 'app.scheduler must not import app.main'; "
        "assert 'mangum' not in sys.modules, 'app.scheduler must not import mangum'"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# Threat 2: a crafted event payload has zero effect (design D45)
# ---------------------------------------------------------------------------


async def test_handler_ignores_every_field_of_the_event(
    recurring_db_sessionmaker, monkeypatch
) -> None:
    """`app.scheduler.handler` reads NO field of `event` — a crafted
    payload naming a victim workspace/recurrence/`today` has zero effect,
    proven by two back-to-back calls (one with the malicious payload, one
    with an empty one) producing byte-identical results against the SAME
    (empty, for this test) due-set. `SessionLocal` is monkeypatched to the
    real ephemeral test Postgres — in production this binds to the
    module-scope engine `app/db.py` builds at cold start (design D1); here
    it is redirected exactly as `tests/recurring/conftest.py`'s
    `app_factory` redirects `get_db` for the HTTP app."""
    from app import scheduler

    monkeypatch.setattr(scheduler, "SessionLocal", recurring_db_sessionmaker)

    malicious_event = {
        "workspace_id": "00000000-0000-0000-0000-000000000000",
        "recurring_transaction_id": "11111111-1111-1111-1111-111111111111",
        "today": "2099-01-01",
    }
    result_a = scheduler.handler(malicious_event, object())
    result_b = scheduler.handler({}, None)
    assert result_a == result_b


# ---------------------------------------------------------------------------
# Threats 3/4: a corrupted account_id — cross-workspace and personal-account
# variants (unreachable through the API, simulated via direct SQL)
# ---------------------------------------------------------------------------


async def _seed_two_workspaces(seed_user, app_factory):
    app = app_factory()
    transport = ASGITransport(app=app)
    owner_a = seed_user(email="threat-a@example.com")
    owner_b = seed_user(email="threat-b@example.com")
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws_a = await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        ws_b = await client.get("/api/workspace", cookies={"walleza_access": cookie_b})
        account_a = await client.post(
            "/api/accounts",
            json={"name": "A Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_a},
        )
        account_b = await client.post(
            "/api/accounts",
            json={"name": "B Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_b},
        )
        personal_b = await client.post(
            "/api/accounts",
            json={"name": "B Personal", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie_b},
        )
    return {
        "workspace_a": uuid.UUID(ws_a.json()["id"]),
        "workspace_b": uuid.UUID(ws_b.json()["id"]),
        "owner_a": owner_a,
        "owner_b": owner_b,
        "account_a": uuid.UUID(account_a.json()["id"]),
        "account_b": uuid.UUID(account_b.json()["id"]),
        "personal_b": uuid.UUID(personal_b.json()["id"]),
    }


def _insert_corrupt_recurring(
    db, *, workspace_id, created_by_user_id, account_id, starts_on: date
) -> uuid.UUID:
    """Direct SQL, deliberately bypassing every service-layer validation —
    the only way a `recurring_transaction` row can ever hold a
    cross-workspace/foreign-owner `account_id`, since
    `app.recurring.service.create_recurring`'s
    `_validate_account_reference` rejects it at the API layer."""
    recurring_id = uuid.uuid4()
    db.execute(
        sa.text(
            "INSERT INTO app.recurring_transaction "
            "(id, workspace_id, account_id, type, amount, repeat_every, period, "
            " starts_on, occurrence_index, next_date, created_by_user_id, "
            " created_at, updated_at) "
            "VALUES (:id, :workspace_id, :account_id, 'expense', 100.00, 1, 'month', "
            " :starts_on, 0, :starts_on, :created_by_user_id, now(), now())"
        ),
        {
            "id": recurring_id,
            "workspace_id": workspace_id,
            "account_id": account_id,
            "starts_on": starts_on,
            "created_by_user_id": created_by_user_id,
        },
    )
    db.commit()
    return recurring_id


async def test_corrupted_cross_workspace_account_id_writes_nothing_and_pauses(
    seed_user, app_factory, recurring_db_sessionmaker
) -> None:
    ctx = await _seed_two_workspaces(seed_user, app_factory)
    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_corrupt_recurring(
            db,
            workspace_id=ctx["workspace_a"],
            created_by_user_id=ctx["owner_a"],
            account_id=ctx["account_b"],  # belongs to workspace B, not A
            starts_on=date(2026, 1, 1),
        )

        outcome = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 5))
        assert outcome == "error"
        assert (
            db.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": ctx["account_b"]},
            ).scalar_one()
            == 0
        )

        row = db.execute(
            sa.text(
                "SELECT occurrence_index, next_date FROM app.recurring_transaction "
                "WHERE id = :id"
            ),
            {"id": recurring_id},
        ).one()
        assert row.occurrence_index == 0
        assert row.next_date == date(2026, 1, 1)
    finally:
        db.close()


async def test_corrupted_foreign_personal_account_writes_nothing_and_pauses(
    seed_user, app_factory, recurring_db_sessionmaker
) -> None:
    """Personal-account variant of threat 3: `account_id` points at a
    PERSONAL account (`is_personal=true`) owned by a different user in a
    different workspace — `visible_accounts(scope)` rejects it on BOTH the
    workspace mismatch and the owner mismatch, same guard, same result."""
    ctx = await _seed_two_workspaces(seed_user, app_factory)
    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_corrupt_recurring(
            db,
            workspace_id=ctx["workspace_a"],
            created_by_user_id=ctx["owner_a"],
            account_id=ctx["personal_b"],  # workspace B's personal account, owned by B
            starts_on=date(2026, 1, 1),
        )

        outcome = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 5))
        assert outcome == "error"
        assert (
            db.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": ctx["personal_b"]},
            ).scalar_one()
            == 0
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Threat 5: the creator's workspace_member row is deleted (design D46)
# ---------------------------------------------------------------------------


async def test_membership_deleted_pauses_and_re_adding_resumes_catchup(
    seed_user, app_factory, recurring_db_sessionmaker
) -> None:
    app = app_factory()
    transport = ASGITransport(app=app)
    owner = seed_user(email="threat-membership@example.com")
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        recurring = await client.post(
            "/api/recurring",
            json={
                "account_id": account.json()["id"],
                "type": "expense",
                "amount": "50.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
            },
            cookies={"walleza_access": cookie},
        )
    recurring_id = uuid.UUID(recurring.json()["id"])
    account_id = uuid.UUID(account.json()["id"])

    db = recurring_db_sessionmaker()
    try:
        db.execute(
            sa.text("DELETE FROM app.workspace_member WHERE user_id = :uid"), {"uid": owner}
        )
        db.commit()

        outcome = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 5))
        assert outcome == "paused"
        assert (
            db.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": account_id},
            ).scalar_one()
            == 0
        )

        member_id = uuid.uuid4()
        workspace_id = db.execute(
            sa.text("SELECT workspace_id FROM app.recurring_transaction WHERE id = :id"),
            {"id": recurring_id},
        ).scalar_one()
        db.execute(
            sa.text(
                "INSERT INTO app.workspace_member (id, workspace_id, user_id, joined_at) "
                "VALUES (:id, :workspace_id, :user_id, now())"
            ),
            {"id": member_id, "workspace_id": workspace_id, "user_id": owner},
        )
        db.commit()

        outcome_after = generation._generate_for_recurrence(
            db, recurring_id, today=date(2026, 1, 5)
        )
        assert outcome_after == "generated"
        assert (
            db.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": account_id},
            ).scalar_one()
            == 1
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Threat 6: a split category deleted/moved out of the workspace mid-run
# ---------------------------------------------------------------------------


async def test_foreign_split_category_rolls_back_the_whole_recurrence(
    seed_user, app_factory, recurring_db_sessionmaker
) -> None:
    ctx = await _seed_two_workspaces(seed_user, app_factory)
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(ctx["owner_a"])

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        category = await client.post(
            "/api/categories",
            json={"name": "Rent", "type": "expense"},
            cookies={"walleza_access": cookie_a},
        )
        category_id = category.json()["id"]
        recurring = await client.post(
            "/api/recurring",
            json={
                "account_id": str(ctx["account_a"]),
                "type": "expense",
                "amount": "100.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
                "splits": [{"category_id": category_id, "amount": "100.00"}],
            },
            cookies={"walleza_access": cookie_a},
        )
    recurring_id = uuid.UUID(recurring.json()["id"])

    db = recurring_db_sessionmaker()
    try:
        foreign_category_b = db.execute(
            sa.text(
                "INSERT INTO app.category (id, workspace_id, name, type, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :workspace_id, 'B Only', 'expense', now(), now()) "
                "RETURNING id"
            ),
            {"workspace_id": ctx["workspace_b"]},
        ).scalar_one()
        db.execute(
            sa.text(
                "UPDATE app.recurring_transaction_split SET category_id = :category_id "
                "WHERE recurring_transaction_id = :id"
            ),
            {"category_id": foreign_category_b, "id": recurring_id},
        )
        db.commit()

        outcome = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 5))
        assert outcome == "error"

        assert (
            db.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": ctx["account_a"]},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                sa.text(
                    "SELECT count(*) FROM app.transaction_category_split s "
                    "JOIN app.transaction t ON t.id = s.transaction_id "
                    "WHERE t.account_id = :account_id"
                ),
                {"account_id": ctx["account_a"]},
            ).scalar_one()
            == 0
        )
        assert (
            db.execute(
                sa.text(
                    "SELECT count(*) FROM app.recurring_occurrence "
                    "WHERE recurring_transaction_id = :id"
                ),
                {"id": recurring_id},
            ).scalar_one()
            == 0
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Concurrency: two overlapping runs against the same due recurrence
# ---------------------------------------------------------------------------


async def test_two_concurrent_sessions_never_both_post_for_the_same_recurrence(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    app = app_factory()
    transport = ASGITransport(app=app)
    owner = seed_user(email="threat-concurrency@example.com")
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        recurring = await client.post(
            "/api/recurring",
            json={
                "account_id": account.json()["id"],
                "type": "expense",
                "amount": "75.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
            },
            cookies={"walleza_access": cookie},
        )
    recurring_id = uuid.UUID(recurring.json()["id"])
    account_id = uuid.UUID(account.json()["id"])

    session_a = recurring_db_sessionmaker()
    session_b = recurring_db_sessionmaker()
    try:
        # Session A holds the row's lock without committing, simulating an
        # in-flight run that has not finished yet.
        session_a.execute(
            sa.text("SELECT id FROM app.recurring_transaction WHERE id = :id FOR UPDATE"),
            {"id": recurring_id},
        )

        outcome_b = generation._generate_for_recurrence(
            session_b, recurring_id, today=date(2026, 1, 5)
        )
        assert outcome_b == "locked"
        assert (
            session_b.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": account_id},
            ).scalar_one()
            == 0
        )

        session_a.rollback()  # release the lock, as a finished/aborted run would

        outcome_a = generation._generate_for_recurrence(
            session_a, recurring_id, today=date(2026, 1, 5)
        )
        assert outcome_a == "generated"
        assert (
            session_a.execute(
                sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
                {"account_id": account_id},
            ).scalar_one()
            == 1
        )
    finally:
        session_a.close()
        session_b.close()


# ---------------------------------------------------------------------------
# 2.16: import-graph assertion — generation never imports app.transfers
# ---------------------------------------------------------------------------


def test_recurring_and_templates_never_import_transfers() -> None:
    for package in ("app/recurring", "app/templates"):
        for source_file in (BACKEND_DIR / package).glob("*.py"):
            text = source_file.read_text()
            assert "app.transfers" not in text, f"{source_file} references app.transfers"
            assert "from app import transfers" not in text
