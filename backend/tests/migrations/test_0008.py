"""RED -> GREEN: `0008_platform_admin` creates `app.platform_admin` with
`user_id` as its PRIMARY KEY, `granted_by_user_id` nullable with
`ON DELETE SET NULL` (design D97), and `downgrade()` drops the table
cleanly. Follows the same real-Postgres harness `test_0007.py` and
`test_0002.py` established.
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


def test_granted_by_set_null_on_granter_deletion(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0008")

        with engine.begin() as conn:
            granter_id = _seed_user(conn, email="granter@example.com")
            grantee_id = _seed_user(conn, email="grantee@example.com")
            conn.execute(
                sa.text(
                    "INSERT INTO app.platform_admin (user_id, granted_at, granted_by_user_id) "
                    "VALUES (:grantee, now(), :granter)"
                ),
                {"grantee": grantee_id, "granter": granter_id},
            )
            conn.execute(
                sa.text("DELETE FROM app.app_user WHERE id = :id"), {"id": granter_id}
            )

        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT granted_by_user_id FROM app.platform_admin WHERE user_id = :id"
                ),
                {"id": grantee_id},
            ).first()
        assert row is not None
        assert row.granted_by_user_id is None
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_user_id_is_primary_key_at_most_one_grant(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0008")

        with engine.begin() as conn:
            user_id = _seed_user(conn, email="dupe@example.com")
            conn.execute(
                sa.text(
                    "INSERT INTO app.platform_admin (user_id, granted_at) VALUES (:id, now())"
                ),
                {"id": user_id},
            )

        violated = False
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.platform_admin (user_id, granted_at) VALUES (:id, now())"
                    ),
                    {"id": user_id},
                )
        except sa.exc.IntegrityError:
            violated = True
        assert violated, "a second grant for the same user_id must violate the PRIMARY KEY"
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_drops_platform_admin_table(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0007")

        inspector = sa.inspect(engine)
        assert "platform_admin" not in inspector.get_table_names(schema="app")
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
