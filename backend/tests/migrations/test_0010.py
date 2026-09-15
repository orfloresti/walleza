"""RED -> GREEN: `0010_admin_capability_columns` adds
`app.app_user.deactivated_at` (nullable, design D101) and
`app.workspace.is_active` (NOT NULL, `server_default=true`, design D106).
Both are additive/inert here — enforcement is Unit 4 — this test only
proves the DDL and its default/nullability shape, and clean reversal.
Follows the same real-Postgres harness `test_0008.py`/`test_0009.py`
established.
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


def test_existing_workspace_defaults_to_active(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0009")

        with engine.begin() as conn:
            owner_id = _seed_user(conn, email="owner@example.com")
            workspace_id = "11111111-1111-1111-1111-111111111111"
            conn.execute(
                sa.text(
                    "INSERT INTO app.workspace (id, name, created_by_user_id, created_at, updated_at) "
                    "VALUES (:id, 'W', :owner, now(), now())"
                ),
                {"id": workspace_id, "owner": owner_id},
            )

        command.upgrade(cfg, "0010")

        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT is_active FROM app.workspace WHERE id = :id"),
                {"id": workspace_id},
            ).first()
        assert row is not None
        assert row.is_active is True
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_deactivated_at_defaults_to_null(
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
            user_id = _seed_user(conn, email="fresh-user@example.com")

        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT deactivated_at FROM app.app_user WHERE id = :id"),
                {"id": user_id},
            ).first()
        assert row is not None
        assert row.deactivated_at is None
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_drops_both_columns(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0009")

        inspector = sa.inspect(engine)
        user_cols = {c["name"] for c in inspector.get_columns("app_user", schema="app")}
        workspace_cols = {c["name"] for c in inspector.get_columns("workspace", schema="app")}
        assert "deactivated_at" not in user_cols
        assert "is_active" not in workspace_cols
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
