"""RED -> GREEN: the baseline Alembic migration creates ONLY the auth-support
tables (`app.app_user`, `app.auth_session`) and no other product/domain
table, per the spec's "Migration Framework with Auth-Only Baseline"
requirement and design D3.

This runs `alembic upgrade head` / `alembic downgrade base` against a REAL,
ephemeral PostgreSQL server — not a mock, not SQLite — per the design's
stated testing strategy ("Alembic upgrade head then downgrade base on a
throwaway Postgres").

Docker is not usable in this sandbox (the docker daemon socket exists but
this user has no `docker` group membership and there is no passwordless
sudo, so `docker ps` fails with a permission error), so this test starts a
real PostgreSQL cluster directly from server binaries (`initdb`/`pg_ctl`)
instead of testcontainers. It looks for those binaries on `PATH` first,
then falls back to a dedicated conda environment. If neither is available
it skips with a clear message rather than silently passing — see
`backend/README.md` "Testing migrations" for how to provision them.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Fallback location documented in backend/README.md ("Testing migrations"):
# `conda create -n pgtest -c conda-forge postgresql`. Only used when no
# `initdb` is already on PATH.
_CONDA_FALLBACK_BIN_DIR = Path.home() / "apps" / "miniconda" / "envs" / "pgtest" / "bin"


def _find_pg_bin_dir() -> str | None:
    override = os.environ.get("WALLEZA_TEST_PG_BIN_DIR")
    if override:
        return override

    which_initdb = shutil.which("initdb")
    if which_initdb:
        return str(Path(which_initdb).parent)

    if (_CONDA_FALLBACK_BIN_DIR / "initdb").exists():
        return str(_CONDA_FALLBACK_BIN_DIR)

    return None


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _EphemeralPostgres:
    """A real, throwaway PostgreSQL server for the lifetime of one test module."""

    def __init__(self, bin_dir: str) -> None:
        self.bin_dir = bin_dir
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-test-")
        self.port = _free_tcp_port()
        self.log_path = os.path.join(self.data_dir, "server.log")

    def _run(self, executable: str, *args: str) -> None:
        exe = os.path.join(self.bin_dir, executable)
        subprocess.run([exe, *args], check=True, capture_output=True, text=True)

    def start(self) -> None:
        self._run(
            "initdb",
            "-D",
            self.data_dir,
            "-U",
            "postgres",
            "-A",
            "trust",
            "--no-sync",
            "--encoding=UTF8",
        )
        self._run(
            "pg_ctl",
            "-D",
            self.data_dir,
            "-l",
            self.log_path,
            "-w",
            "-o",
            f"-p {self.port} -k {self.data_dir} -c listen_addresses=127.0.0.1",
            "start",
        )

    def stop(self) -> None:
        try:
            self._run("pg_ctl", "-D", self.data_dir, "-m", "immediate", "stop")
        except subprocess.CalledProcessError:
            pass
        shutil.rmtree(self.data_dir, ignore_errors=True)

    @property
    def admin_url(self) -> str:
        return f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/postgres"


@pytest.fixture(scope="module")
def real_postgres() -> Iterator[_EphemeralPostgres]:
    bin_dir = _find_pg_bin_dir()
    if not bin_dir:
        pytest.skip(
            "No real PostgreSQL server binaries available: no Docker socket "
            "access in this sandbox (permission denied, no `docker` group "
            "membership, no passwordless sudo) and no `initdb`/`pg_ctl` on "
            "PATH. Provision a real server locally, e.g.: "
            "`conda create -y -n pgtest -c conda-forge postgresql`, or set "
            "WALLEZA_TEST_PG_BIN_DIR to a directory containing those "
            "binaries. See backend/README.md 'Testing migrations'."
        )

    pg = _EphemeralPostgres(bin_dir)
    pg.start()
    try:
        yield pg
    finally:
        pg.stop()


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def test_baseline_creates_only_auth_tables_and_downgrades_cleanly(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        # GREEN: running the baseline against an empty, real database
        # succeeds and creates exactly the two auth-support tables.
        command.upgrade(cfg, "head")

        inspector = sa.inspect(engine)
        assert "app" in inspector.get_schema_names()
        # Alembic's own bookkeeping table (`alembic_version`) also lives in
        # `app` (env.py `VERSION_TABLE_SCHEMA`) — it is framework plumbing,
        # not a product/domain table, so it is expected here alongside the
        # two auth-support tables the spec requires.
        assert set(inspector.get_table_names(schema="app")) == {
            "app_user",
            "auth_session",
            "alembic_version",
        }

        # No other product/domain table was created anywhere else either
        # (spec: baseline MUST NOT define any non-auth table in this phase).
        with engine.connect() as conn:
            other_tables = conn.execute(
                sa.text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'app')"
                )
            ).fetchall()
        assert other_tables == []

        # The FK from auth_session.user_id to app_user.id is real and enforced.
        with engine.connect() as conn:
            fk_violation_raised = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.auth_session "
                        "(id, user_id, refresh_hash, family_id, expires_at) "
                        "VALUES (gen_random_uuid(), gen_random_uuid(), 'x', "
                        "gen_random_uuid(), now())"
                    )
                )
                conn.commit()
            except sa.exc.IntegrityError:
                fk_violation_raised = True
                conn.rollback()
            assert fk_violation_raised, (
                "auth_session.user_id must be a real, enforced FK to app_user.id"
            )

        # downgrade base must cleanly remove both auth tables. The `app`
        # schema itself is left in place afterwards because Alembic's own
        # bookkeeping table (`alembic_version`) lives there too (env.py
        # `VERSION_TABLE_SCHEMA`) — dropping the schema would destroy
        # Alembic's own tracking table, not just this migration's tables.
        command.downgrade(cfg, "base")

        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == {
            "alembic_version"
        }
    finally:
        engine.dispose()
        get_settings.cache_clear()
