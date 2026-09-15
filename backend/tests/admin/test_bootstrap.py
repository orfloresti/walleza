"""RED -> GREEN, Phase 8 design D107, spec platform-admin domain
"Bootstrap Idempotency" requirement (tasks.md Unit 2 task 2.10): all
three scenarios — no-op when already seeded, no-op with a clear message
when the target user has never logged in, and a successful grant when
the email matches a real `app_user` row — exercised directly against
`app.admin.bootstrap.run_bootstrap` over a real connection.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.admin.bootstrap import ENV_VAR, run_bootstrap


@pytest.fixture(autouse=True)
def _clean_admin_and_user_tables(admin_db_sessionmaker):
    """`admin_db_sessionmaker` is module-scoped (one real ephemeral
    Postgres shared across this file's tests); each test needs a clean
    `platform_admin`/`app_user` slate so one test's grant/seed never
    leaks into the next."""
    engine = admin_db_sessionmaker.kw["bind"]
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM app.platform_admin"))
        conn.execute(sa.text("DELETE FROM app.app_user"))
    yield


def test_noop_when_env_var_unset(admin_db_sessionmaker, monkeypatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    engine = admin_db_sessionmaker.kw["bind"]
    with engine.begin() as conn:
        message = run_bootstrap(conn)
    assert "skipping" in message
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
    assert count == 0


def test_noop_when_table_already_seeded(
    seed_user, grant_platform_admin, admin_db_sessionmaker, monkeypatch
) -> None:
    existing_admin = seed_user(email="already-admin@example.com")
    grant_platform_admin(user_id=existing_admin)
    monkeypatch.setenv(ENV_VAR, "someone-else@example.com")
    engine = admin_db_sessionmaker.kw["bind"]

    with engine.begin() as conn:
        message = run_bootstrap(conn)

    assert "already seeded" in message
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
    assert count == 1


def test_noop_with_clear_message_when_user_has_never_logged_in(
    admin_db_sessionmaker, monkeypatch
) -> None:
    monkeypatch.setenv(ENV_VAR, "never-logged-in@example.com")
    engine = admin_db_sessionmaker.kw["bind"]

    with engine.begin() as conn:
        message = run_bootstrap(conn)

    assert "never-logged-in@example.com" in message
    assert "must sign in" in message
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
    assert count == 0


def test_successful_bootstrap_grants_admin_with_no_granter(
    seed_user, admin_db_sessionmaker, monkeypatch
) -> None:
    user_id = seed_user(email="bootstrap-target@example.com")
    monkeypatch.setenv(ENV_VAR, "bootstrap-target@example.com")
    engine = admin_db_sessionmaker.kw["bind"]

    with engine.begin() as conn:
        message = run_bootstrap(conn)

    assert "bootstrap-target@example.com" in message
    with engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT user_id, granted_by_user_id FROM app.platform_admin WHERE user_id = :uid"
            ),
            {"uid": user_id},
        ).first()
    assert row is not None
    assert row.granted_by_user_id is None


def test_bootstrap_is_idempotent_across_repeated_runs(
    seed_user, admin_db_sessionmaker, monkeypatch
) -> None:
    seed_user(email="idempotent-target@example.com")
    monkeypatch.setenv(ENV_VAR, "idempotent-target@example.com")
    engine = admin_db_sessionmaker.kw["bind"]

    with engine.begin() as conn:
        run_bootstrap(conn)
    with engine.begin() as conn:
        run_bootstrap(conn)

    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
    assert count == 1
