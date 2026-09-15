"""RED -> GREEN: `0009_bootstrap_platform_admin` delegates to
`app.admin.bootstrap.run_bootstrap` at `upgrade()` time, and
`downgrade()` removes only the row it itself inserted. Follows the same
real-Postgres harness `test_0007.py`/`test_0008.py` established.
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


def test_upgrade_grants_matching_user_and_downgrade_removes_only_that_row(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    monkeypatch.setenv("INITIAL_PLATFORM_ADMIN_EMAIL", "bootstrap-migration@example.com")
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0008")

        with engine.begin() as conn:
            user_id = _seed_user(conn, email="bootstrap-migration@example.com")

        command.upgrade(cfg, "0009")

        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT note FROM app.platform_admin WHERE user_id = :id"),
                {"id": user_id},
            ).first()
        assert row is not None
        assert row.note == "bootstrap via INITIAL_PLATFORM_ADMIN_EMAIL"

        command.downgrade(cfg, "0008")

        with engine.connect() as conn:
            count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
        assert count == 0
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
        monkeypatch.delenv("INITIAL_PLATFORM_ADMIN_EMAIL", raising=False)


def test_upgrade_noop_when_no_matching_user(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    monkeypatch.setenv("INITIAL_PLATFORM_ADMIN_EMAIL", "never-signed-in@example.com")
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            count = conn.execute(sa.text("SELECT count(*) FROM app.platform_admin")).scalar()
        assert count == 0
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
        monkeypatch.delenv("INITIAL_PLATFORM_ADMIN_EMAIL", raising=False)
