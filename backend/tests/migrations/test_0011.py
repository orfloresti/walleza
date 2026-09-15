"""RED -> GREEN: `0011_audit_log` creates `app.audit_log` with the exact
shape design D102 requires — append-only (no update/delete path is even
possible to prove here; that is `tests/audit/test_audit_log.py`'s job),
nullable `SET NULL` FKs on `actor_user_id`/`workspace_id`, and a CHECK
constraint enumerating the action catalog. Follows the same real-Postgres
harness `test_0008.py`/`test_0010.py` established.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.migrations.test_0007 import _EphemeralPostgres, _find_pg_bin_dir, _seed_user

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


@pytest.fixture(scope="module")
def real_postgres() -> Iterator[_EphemeralPostgres]:
    bin_dir = _find_pg_bin_dir()
    if not bin_dir:
        pytest.skip(
            "No real PostgreSQL server binaries available; see "
            "backend/README.md 'Testing migrations'."
        )
    pg = _EphemeralPostgres(bin_dir)
    pg.start()
    try:
        yield pg
    finally:
        pg.stop()


def test_audit_row_insert_and_shape(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with engine.begin() as conn:
            actor_id = _seed_user(conn, email="actor@example.com")
            row = conn.execute(
                sa.text(
                    "INSERT INTO app.audit_log "
                    "(id, created_at, actor_user_id, actor_was_platform_admin, "
                    "action, target_type, target_id, workspace_id, metadata) "
                    "VALUES (gen_random_uuid(), now(), :actor, false, "
                    "'workspace.renamed', 'workspace', gen_random_uuid(), NULL, "
                    "'{}'::jsonb) RETURNING id, metadata"
                ),
                {"actor": actor_id},
            ).first()
        assert row is not None
        assert row.metadata == {}
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_invalid_action_rejected_by_check_constraint(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO app.audit_log "
                    "(id, created_at, actor_user_id, actor_was_platform_admin, "
                    "action, target_type, target_id, workspace_id, metadata) "
                    "VALUES (gen_random_uuid(), now(), NULL, false, "
                    "'not.a.real.action', 'workspace', NULL, NULL, '{}'::jsonb)"
                )
            )
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_actor_user_deletion_sets_null_not_cascade(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with engine.begin() as conn:
            actor_id = _seed_user(conn, email="doomed-actor@example.com")
            audit_id = conn.execute(
                sa.text(
                    "INSERT INTO app.audit_log "
                    "(id, created_at, actor_user_id, actor_was_platform_admin, "
                    "action, target_type, target_id, workspace_id, metadata) "
                    "VALUES (gen_random_uuid(), now(), :actor, false, "
                    "'platform.user_deactivated', 'user', gen_random_uuid(), NULL, "
                    "'{}'::jsonb) RETURNING id"
                ),
                {"actor": actor_id},
            ).scalar_one()
            conn.execute(sa.text("DELETE FROM app.app_user WHERE id = :id"), {"id": actor_id})

        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT actor_user_id FROM app.audit_log WHERE id = :id"),
                {"id": audit_id},
            ).first()
        assert row is not None
        assert row.actor_user_id is None
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_drops_audit_log_table(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0010")

        inspector = sa.inspect(engine)
        assert "audit_log" not in inspector.get_table_names(schema="app")
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
