"""RED -> GREEN: occurrence generation core (design D45-D49,
`scheduled-occurrence-generation` capability, tasks.md 2.1-2.19).

Generation is always called DIRECTLY against a real ephemeral Postgres —
never through HTTP (design's own Testing Strategy table) — reusing
`tests/recurring/conftest.py`'s MODULE-scoped `recurring_db_sessionmaker`
harness. Account/category setup goes through the real cookie path
(`app_factory`/`seed_user`), exactly like `test_crud.py`; the recurrence
itself is also created through `POST /api/recurring` so
`starts_on`/`period`/`repeat_every`/`ends_on` are exercised through the
real validated surface.

Because the harness's Postgres instance is shared across every test in
this module (started once per module, not per test — the same real-DB
tradeoff `test_0005.py` and friends already make), most tests call
`generation._generate_for_recurrence(db, recurring_id, today=...)`
directly rather than the outer `generation.run`: that function processes
ONLY the one named recurrence, so a test's assertions are never affected
by another test's own (deliberately cross-workspace, by design)
recurrences also being "due" at whatever date that other test happens to
use. `generation.run`'s own cross-recurrence scanning/aggregation
behavior — including the literal "running generation.run twice" RED
test — is covered separately, in its own reserved date window (year
2030) that no other test in this module touches, so it stays isolated
regardless of test order or how many other recurrences accumulate.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.recurring import generation
from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str, *, name: str = "Checking") -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_recurring(
    client,
    cookie: str,
    *,
    account_id: str,
    amount: str = "1200.00",
    repeat_every: int = 1,
    period: str = "month",
    starts_on: str,
    ends_on: str | None = None,
) -> str:
    payload = {
        "account_id": account_id,
        "type": "expense",
        "amount": amount,
        "repeat_every": repeat_every,
        "period": period,
        "starts_on": starts_on,
        "notes": "rent",
    }
    if ends_on is not None:
        payload["ends_on"] = ends_on
    response = await client.post(
        "/api/recurring", json=payload, cookies={"walleza_access": cookie}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _seed_recurring(app_factory, seed_user, *, email: str, starts_on: str, **kwargs):
    app = app_factory()
    transport = ASGITransport(app=app)
    owner = seed_user(email=email)
    cookie = _cookie_for(owner)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        recurring_id = await _create_recurring(
            client, cookie, account_id=account_id, starts_on=starts_on, **kwargs
        )
    return uuid.UUID(recurring_id), uuid.UUID(account_id), owner


def _transaction_count_for(db, account_id: uuid.UUID) -> int:
    return db.execute(
        sa.text("SELECT count(*) FROM app.transaction WHERE account_id = :account_id"),
        {"account_id": account_id},
    ).scalar_one()


def _cursor_for(db, recurring_id: uuid.UUID):
    return db.execute(
        sa.text(
            "SELECT occurrence_index, next_date FROM app.recurring_transaction WHERE id = :id"
        ),
        {"id": recurring_id},
    ).one()


async def test_due_recurrence_generates_one_transaction_and_advances_next_date(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    recurring_id, account_id, _ = await _seed_recurring(
        app_factory, seed_user, email="gen-due@example.com", starts_on="2026-01-15"
    )

    db = recurring_db_sessionmaker()
    try:
        outcome = generation._generate_for_recurrence(
            db, recurring_id, today=date(2026, 1, 20)
        )
        assert outcome == "generated"
        assert _transaction_count_for(db, account_id) == 1

        row = db.execute(
            sa.text(
                "SELECT account_id, type, amount, occurred_on FROM app.transaction "
                "WHERE account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        assert row.type == "expense"
        assert row.amount == Decimal("1200.00")
        assert row.occurred_on == date(2026, 1, 15)

        cursor = _cursor_for(db, recurring_id)
        assert cursor.occurrence_index == 1
        assert cursor.next_date == date(2026, 2, 15)
    finally:
        db.close()


async def test_recurrence_past_ends_on_generates_nothing(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    """`ends_on` is inclusive (design's own Data Flow snippet: `break if
    ... occ > r.ends_on`, never `>=`) — a recurrence's LAST allowed
    occurrence lands exactly ON `ends_on` and still generates; it is the
    occurrence AFTER that which is excluded. This recurrence therefore
    generates its one allowed occurrence first, then is proven to
    generate nothing further once genuinely past its end."""
    recurring_id, account_id, _ = await _seed_recurring(
        app_factory,
        seed_user,
        email="gen-ended@example.com",
        starts_on="2026-01-01",
        ends_on="2026-01-01",
    )

    db = recurring_db_sessionmaker()
    try:
        first = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 1))
        assert first == "generated"

        second = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 6, 1))
        assert second == "no_due_occurrence"

        assert _transaction_count_for(db, account_id) == 1
        cursor = _cursor_for(db, recurring_id)
        assert cursor.occurrence_index == 1
        assert cursor.next_date == date(2026, 2, 1)
    finally:
        db.close()


async def test_run_scans_and_is_idempotent_on_rerun(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    """The literal RED test (design RED #2): `generation.run(db,
    today=...)` called TWICE with the same `today` produces zero
    additional transactions for THIS recurrence, and the aggregate
    `generated` count is zero on the second call.

    This module's `recurring_db_sessionmaker` is shared (module-scoped)
    across every test in this file, and `run`'s own due-scan is
    deliberately cross-workspace/global by design — so other tests' own
    recurrences are legitimately still "due" and get reprocessed by any
    `run()` call here too. The second-call-generates-nothing assertion
    below is nonetheless contamination-proof: `run` is a pure function of
    `(db state, today)`, so calling it twice with the IDENTICAL `today`
    can never newly "generate" on the second call for ANY row, whether
    seeded by this test or a previous one — each row either already
    advanced its cursor past `today` on the first call (no longer due), or
    deterministically produced the same non-generating outcome both
    times (paused/errored/already-ended rows reprocess identically)."""
    recurring_id, account_id, _ = await _seed_recurring(
        app_factory, seed_user, email="gen-run-idempotent@example.com", starts_on="2030-01-15"
    )

    db = recurring_db_sessionmaker()
    try:
        first = generation.run(db, today=date(2030, 1, 20))
        assert first["generated"] >= 1
        assert _transaction_count_for(db, account_id) == 1

        second = generation.run(db, today=date(2030, 1, 20))
        assert second["generated"] == 0
        assert _transaction_count_for(db, account_id) == 1

        occurrence_count = db.execute(
            sa.text(
                "SELECT count(*) FROM app.recurring_occurrence "
                "WHERE recurring_transaction_id = :id"
            ),
            {"id": recurring_id},
        ).scalar_one()
        assert occurrence_count == 1
    finally:
        db.close()


async def test_dormant_three_periods_catches_up_all_three_in_one_run(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    recurring_id, account_id, _ = await _seed_recurring(
        app_factory, seed_user, email="gen-catchup3@example.com", starts_on="2025-11-15"
    )

    # `today` is one day BEFORE the 4th monthly occurrence (2026-02-15) so
    # exactly 3 occurrences are due (`occ <= today` is inclusive, design's
    # own Data Flow snippet) — proving 3 missed periods catch up in one run,
    # not 4.
    db = recurring_db_sessionmaker()
    try:
        outcome = generation._generate_for_recurrence(
            db, recurring_id, today=date(2026, 2, 14)
        )
        assert outcome == "generated"

        occurred_on_dates = [
            row.occurred_on
            for row in db.execute(
                sa.text(
                    "SELECT occurred_on FROM app.transaction "
                    "WHERE account_id = :account_id ORDER BY occurred_on"
                ),
                {"account_id": account_id},
            )
        ]
        assert occurred_on_dates == [date(2025, 11, 15), date(2025, 12, 15), date(2026, 1, 15)]

        again = generation._generate_for_recurrence(db, recurring_id, today=date(2026, 2, 14))
        assert again == "no_due_occurrence"
        assert _transaction_count_for(db, account_id) == 3
    finally:
        db.close()


async def test_catchup_cap_pauses_and_a_second_run_continues(
    app_factory, seed_user, recurring_db_sessionmaker, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_GENERATION_MAX_CATCHUP_PER_RUN", "5")
    get_settings.cache_clear()
    try:
        recurring_id, account_id, _ = await _seed_recurring(
            app_factory,
            seed_user,
            email="gen-cap@example.com",
            starts_on="2026-01-01",
            period="day",
            repeat_every=1,
        )

        db = recurring_db_sessionmaker()
        try:
            today = date(2026, 1, 9)  # 9 due daily occurrences (indices 0..8)
            first = generation._generate_for_recurrence(db, recurring_id, today=today)
            assert first == "generated"

            cursor = _cursor_for(db, recurring_id)
            assert cursor.occurrence_index == 5  # PAUSED at the cap, not fast-forwarded
            assert cursor.next_date == date(2026, 1, 6)
            assert _transaction_count_for(db, account_id) == 5

            second = generation._generate_for_recurrence(db, recurring_id, today=today)
            assert second == "generated"

            cursor_after = _cursor_for(db, recurring_id)
            assert cursor_after.occurrence_index == 9
            assert cursor_after.next_date == date(2026, 1, 10)
            assert _transaction_count_for(db, account_id) == 9
        finally:
            db.close()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_deleted_generated_transaction_is_not_resurrected(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    """Design D47/RED #7: the `recurring_occurrence` PRIMARY KEY is the
    idempotency authority, independent of `transaction_id`'s nullness.
    The cursor alone would never revisit an already-passed occurrence, so
    this test forces a re-visit by resetting the cursor directly via raw
    SQL — simulating the only way this scenario could ever arise (a
    corrupted/reset cursor), exactly mirroring how the threat-matrix tests
    simulate a corrupted `account_id` via direct SQL."""
    recurring_id, account_id, _ = await _seed_recurring(
        app_factory, seed_user, email="gen-tombstone@example.com", starts_on="2026-01-15"
    )

    db = recurring_db_sessionmaker()
    try:
        generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 20))
        assert _transaction_count_for(db, account_id) == 1

        db.execute(
            sa.text("DELETE FROM app.transaction WHERE account_id = :account_id"),
            {"account_id": account_id},
        )
        db.commit()

        occurrence = db.execute(
            sa.text(
                "SELECT transaction_id FROM app.recurring_occurrence "
                "WHERE recurring_transaction_id = :id"
            ),
            {"id": recurring_id},
        ).one()
        assert occurrence.transaction_id is None  # tombstone: ON DELETE SET NULL

        db.execute(
            sa.text(
                "UPDATE app.recurring_transaction "
                "SET occurrence_index = 0, next_date = '2026-01-15' WHERE id = :id"
            ),
            {"id": recurring_id},
        )
        db.commit()

        generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 20))

        assert _transaction_count_for(db, account_id) == 0
        occurrence_after = db.execute(
            sa.text(
                "SELECT transaction_id FROM app.recurring_occurrence "
                "WHERE recurring_transaction_id = :id"
            ),
            {"id": recurring_id},
        ).one()
        assert occurrence_after.transaction_id is None
    finally:
        db.close()


async def test_generated_transaction_is_shaped_identically_to_a_manual_one(
    app_factory, seed_user, recurring_db_sessionmaker
) -> None:
    """Design RED #9: no provenance field leaks onto the transaction row —
    a generated transaction has the exact same column set a manual one
    does, and (per this PR's judgment call) is attributed to the
    recurrence's own creator, never a NULL or sentinel creator id."""
    recurring_id, account_id, owner = await _seed_recurring(
        app_factory, seed_user, email="gen-shape@example.com", starts_on="2026-01-15"
    )

    db = recurring_db_sessionmaker()
    try:
        generation._generate_for_recurrence(db, recurring_id, today=date(2026, 1, 20))
        columns = {
            row[0]
            for row in db.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'app' AND table_name = 'transaction'"
                )
            )
        }
        assert "recurring_transaction_id" not in columns
        assert "generated" not in columns
        assert "source" not in columns

        row = db.execute(
            sa.text(
                "SELECT created_by_user_id, checked FROM app.transaction "
                "WHERE account_id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        assert row.created_by_user_id == owner
        assert row.checked is False
    finally:
        db.close()


@pytest.mark.parametrize(
    "anchor,period,n,expected",
    [
        (date(2026, 1, 31), "month", 0, date(2026, 1, 31)),
        (date(2026, 1, 31), "month", 1, date(2026, 2, 28)),
        (date(2026, 1, 31), "month", 2, date(2026, 3, 31)),
        (date(2026, 1, 31), "month", 3, date(2026, 4, 30)),
        (date(2024, 1, 31), "month", 1, date(2024, 2, 29)),  # leap year
        (date(2026, 1, 31), "year", 1, date(2027, 1, 31)),
        (date(2024, 2, 29), "year", 1, date(2025, 2, 28)),  # leap-day anchor, non-leap target
        (date(2026, 1, 1), "day", 10, date(2026, 1, 11)),
        (date(2026, 1, 1), "week", 3, date(2026, 1, 22)),
    ],
)
def test_shift_is_anchor_based_and_never_drifts(
    anchor: date, period: str, n: int, expected: date
) -> None:
    assert generation.shift(anchor, period, n) == expected


def test_shift_iterative_would_have_drifted_but_anchor_based_does_not() -> None:
    """Non-drift assertion over 36 successive months from a Jan-31 anchor:
    iterative advancement (previous_next_date + 1 month) would clamp Feb's
    28 forward forever (Jan 31 -> Feb 28 -> Mar 28 -> ...); the anchor-based
    `shift` recovers the 31st every month that has one."""
    anchor = date(2026, 1, 31)
    results = [generation.shift(anchor, "month", n) for n in range(36)]
    months_with_31_days = {1, 3, 5, 7, 8, 10, 12}
    for offset, occurrence in enumerate(results):
        if occurrence.month in months_with_31_days:
            assert occurrence.day == 31, f"month {offset} lost its day-31 anchor: {occurrence}"
