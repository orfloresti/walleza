"""RED -> GREEN: reminders (design D54, `recurring-reminders` capability,
tasks.md 4.7-4.12).

`app.notifications.ses.sesv2` is monkeypatched at MODULE level with a fake
client (mirroring `app.storage`'s monkeypatchable pattern, per design's
File Changes table entry for `app/notifications/ses.py`) — no real AWS
call is ever made by this suite.

Reminders are always exercised DIRECTLY against a real ephemeral Postgres,
never through HTTP (mirrors `test_generation.py`'s own discipline: Pass B
has no REST contract at all). Account/workspace setup goes through the
real cookie path (`app_factory`/`seed_user`); the recurrence rows
themselves are inserted via direct SQL so every reminder-relevant column
(`next_date`, `reminder_days_before`, `last_reminded_for_date`, `ends_on`,
`reminder_locale`) is fully test-controlled, mirroring
`test_generation_threats.py`'s own `_insert_corrupt_recurring` precedent.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.notifications import ses, templates
from app.recurring import generation
from app.security import issue_access_token

TODAY = date(2026, 6, 15)


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


class _FakeSES:
    """Records every `send_email` call instead of reaching real AWS,
    monkeypatched in place of `app.notifications.ses.sesv2` — the SAME
    module-level attribute the real client is bound to, exactly as
    `app/storage.py`'s tests are expected to monkeypatch `_s3_client`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_email(self, **kwargs: object) -> dict[str, str]:
        self.calls.append(kwargs)
        return {"MessageId": f"fake-{len(self.calls)}"}


async def _bootstrap_workspace_and_account(
    app_factory, cookie: str, *, name: str = "Checking"
) -> tuple[uuid.UUID, uuid.UUID]:
    app = app_factory()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": name, "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
    return uuid.UUID(ws.json()["id"]), uuid.UUID(account.json()["id"])


def _insert_recurring(
    db,
    *,
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    next_date: date,
    starts_on: date | None = None,
    ends_on: date | None = None,
    reminder_days_before: int | None,
    last_reminded_for_date: date | None = None,
    reminder_locale: str = "en",
    amount: Decimal = Decimal("500.00"),
) -> uuid.UUID:
    recurring_id = uuid.uuid4()
    db.execute(
        sa.text(
            "INSERT INTO app.recurring_transaction "
            "(id, workspace_id, account_id, type, amount, repeat_every, period, "
            " starts_on, occurrence_index, next_date, ends_on, reminder_days_before, "
            " last_reminded_for_date, reminder_locale, created_by_user_id, "
            " created_at, updated_at) "
            "VALUES (:id, :workspace_id, :account_id, 'expense', :amount, 1, 'month', "
            " :starts_on, 0, :next_date, :ends_on, :reminder_days_before, "
            " :last_reminded_for_date, :reminder_locale, :created_by_user_id, now(), now())"
        ),
        {
            "id": recurring_id,
            "workspace_id": workspace_id,
            "account_id": account_id,
            "amount": amount,
            "starts_on": starts_on or next_date,
            "next_date": next_date,
            "ends_on": ends_on,
            "reminder_days_before": reminder_days_before,
            "last_reminded_for_date": last_reminded_for_date,
            "reminder_locale": reminder_locale,
            "created_by_user_id": created_by_user_id,
        },
    )
    db.commit()
    return recurring_id


# ---------------------------------------------------------------------------
# 4.7: reminder fires ahead of the due date; NULL reminder_days_before never sends
# ---------------------------------------------------------------------------


async def test_reminder_sends_when_within_window(
    seed_user, app_factory, recurring_db_sessionmaker, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-sends@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(app_factory, cookie)

    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            next_date=TODAY + timedelta(days=3),
            reminder_days_before=3,
        )

        outcome = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert outcome == "sent"
        assert len(fake.calls) == 1
        assert fake.calls[0]["Destination"] == {"ToAddresses": ["reminder-sends@example.com"]}

        row = db.execute(
            sa.text(
                "SELECT last_reminded_for_date, next_date FROM app.recurring_transaction "
                "WHERE id = :id"
            ),
            {"id": recurring_id},
        ).one()
        assert row.last_reminded_for_date == row.next_date
    finally:
        db.close()


async def test_null_reminder_days_before_never_sends(
    seed_user, app_factory, recurring_db_sessionmaker, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-null@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(app_factory, cookie)

    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            next_date=TODAY + timedelta(days=1),
            reminder_days_before=None,
        )

        assert recurring_id not in generation._due_reminder_ids(db, today=TODAY)
        counts = generation.run_reminders(db, today=TODAY)
        assert counts["sent"] == 0
        assert not fake.calls
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.8: send-once per due date — a same-day re-run never resends
# ---------------------------------------------------------------------------


async def test_reminder_is_not_resent_on_same_day_rerun(
    seed_user, app_factory, recurring_db_sessionmaker, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-rerun@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(app_factory, cookie)

    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            next_date=TODAY + timedelta(days=2),
            reminder_days_before=2,
        )

        first = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert first == "sent"
        assert len(fake.calls) == 1

        second = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert second == "already_sent"
        assert len(fake.calls) == 1  # no additional send

        row = db.execute(
            sa.text(
                "SELECT last_reminded_for_date FROM app.recurring_transaction WHERE id = :id"
            ),
            {"id": recurring_id},
        ).one()
        assert row.last_reminded_for_date == TODAY + timedelta(days=2)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.9: a recurrence past ends_on receives no reminder
# ---------------------------------------------------------------------------


async def test_ended_recurrence_receives_no_reminder(
    seed_user, app_factory, recurring_db_sessionmaker, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-ended@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(app_factory, cookie)

    db = recurring_db_sessionmaker()
    try:
        # `next_date` (the cursor) sits AHEAD of `ends_on` — the same state
        # generation's own catch-up loop leaves behind once a recurrence has
        # fully generated past its end (design's module docstring: the
        # cursor still advances to the next, unreachable occurrence).
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            starts_on=TODAY - timedelta(days=60),
            ends_on=TODAY - timedelta(days=1),
            next_date=TODAY + timedelta(days=2),
            reminder_days_before=5,
        )

        outcome = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert outcome == "paused"
        assert not fake.calls
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.10: a shared-account recurrence's reminder goes only to its creator
# ---------------------------------------------------------------------------


async def test_shared_account_reminder_goes_only_to_creator(
    seed_user, app_factory, recurring_db_sessionmaker, db_session, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-owner@example.com")
    other_member = seed_user(email="reminder-other-member@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(
        app_factory, cookie, name="Shared Checking"
    )

    # Add `other_member` to the SAME workspace directly (mirrors
    # `test_generation_threats.py`'s membership re-add pattern) — they can
    # see the recurrence (shared, non-personal account) but must never
    # receive its reminder.
    db_session.execute(
        sa.text(
            "INSERT INTO app.workspace_member (id, workspace_id, user_id, joined_at) "
            "VALUES (:id, :workspace_id, :user_id, now())"
        ),
        {"id": uuid.uuid4(), "workspace_id": workspace_id, "user_id": other_member},
    )
    db_session.commit()

    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            next_date=TODAY + timedelta(days=1),
            reminder_days_before=1,
        )

        outcome = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert outcome == "sent"
        assert len(fake.calls) == 1
        assert fake.calls[0]["Destination"] == {"ToAddresses": ["reminder-owner@example.com"]}
        assert "reminder-other-member@example.com" not in str(fake.calls[0])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.11: subject withholds the amount; body may include it
# ---------------------------------------------------------------------------


def test_rendered_subject_contains_none_of_the_amounts_digits() -> None:
    for locale in ("en", "es"):
        amount = Decimal("1234.56")
        subject, body = templates.render_reminder(
            locale=locale,
            type="expense",
            amount=amount,
            currency="USD",
            account_name="Rent Checking",
            occurrence_date=date(2026, 7, 1),
            web_app_url="https://walleza.example.com",
            category_names=["Housing"],
        )
        digits = {ch for ch in str(amount) if ch.isdigit()}
        assert digits, "sanity: the formatted amount must actually contain digits"
        assert not (digits & set(subject)), f"subject leaked an amount digit: {subject!r}"
        assert any(d in body for d in digits), "sanity: body should still carry the amount"


async def test_send_email_reminder_call_carries_no_amount_digit_in_subject(
    seed_user, app_factory, recurring_db_sessionmaker, monkeypatch
) -> None:
    fake = _FakeSES()
    monkeypatch.setattr(ses, "sesv2", fake)

    owner = seed_user(email="reminder-subject@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _bootstrap_workspace_and_account(app_factory, cookie)

    db = recurring_db_sessionmaker()
    try:
        recurring_id = _insert_recurring(
            db,
            workspace_id=workspace_id,
            account_id=account_id,
            created_by_user_id=owner,
            next_date=TODAY + timedelta(days=1),
            reminder_days_before=1,
            amount=Decimal("789.10"),
        )

        outcome = generation._send_reminder_for_recurrence(db, recurring_id, today=TODAY)
        assert outcome == "sent"
        subject = fake.calls[0]["Content"]["Simple"]["Subject"]["Data"]  # type: ignore[index]
        digits = {ch for ch in "789.10" if ch.isdigit()}
        assert not (digits & set(subject))
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4.12: threat case 7 — the public HTTP role never gains email-sending
# capability, and app.notifications is never in app.main's import closure
# ---------------------------------------------------------------------------


def test_lambda_exec_role_never_gains_ses_permissions() -> None:
    infra_dir = generation.__file__
    from pathlib import Path

    infra_dir = Path(infra_dir).resolve().parents[3] / "infra"
    lambda_tf = (infra_dir / "lambda.tf").read_text()
    assert "ses:" not in lambda_tf, "lambda.tf (the public HTTP role) must never gain ses: actions"

    ses_tf = (infra_dir / "ses.tf").read_text()
    non_comment_lines = [
        line for line in ses_tf.splitlines() if not line.strip().startswith("#")
    ]
    non_comment_text = "\n".join(non_comment_lines)
    assert "aws_iam_role.scheduler_exec" in non_comment_text
    assert "aws_iam_role.lambda_exec" not in non_comment_text


def test_notifications_never_imported_by_app_main() -> None:
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(generation.__file__).resolve().parents[2]
    script = (
        "import sys; import app.main; "
        "assert 'app.notifications' not in sys.modules, "
        "'app.main must not import app.notifications'"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
