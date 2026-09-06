"""Shared fixtures for auth tests.

`auth_db_sessionmaker` provisions a REAL, ephemeral PostgreSQL server (not
a mock, not SQLite) with the baseline schema applied, following exactly
the same real-Postgres pattern already established in
`backend/tests/migrations/test_baseline.py` — refresh-token rotation and
reuse detection are security-critical and must be proven against real FK
constraints and real transactions, not an in-memory stand-in.

This intentionally duplicates (rather than imports) the small
`_EphemeralPostgres` helper from `test_baseline.py`: that file belongs to
the already-verified PR2b migrations slice, and this PR keeps its own
test infrastructure self-contained rather than reaching into another
PR's test module.
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
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

# Same fallback documented in backend/README.md "Testing migrations".
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
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-auth-test-")
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


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


@pytest.fixture(scope="module")
def auth_db_sessionmaker() -> Iterator[sessionmaker]:
    """A `sessionmaker` bound to a real, ephemeral Postgres with the
    baseline auth schema already applied via `alembic upgrade head`.

    Skips (rather than silently passing or falling back to a mock) when
    no real PostgreSQL server binaries are available — see
    `backend/README.md` "Testing migrations" for provisioning.
    """
    bin_dir = _find_pg_bin_dir()
    if not bin_dir:
        pytest.skip(
            "No real PostgreSQL server binaries available: no Docker socket "
            "access in this sandbox and no `initdb`/`pg_ctl` on PATH. "
            "Provision one locally, e.g.: "
            "`conda create -y -n pgtest -c conda-forge postgresql`, or set "
            "WALLEZA_TEST_PG_BIN_DIR. See backend/README.md 'Testing migrations'."
        )

    from app.config import get_settings

    pg = _EphemeralPostgres(bin_dir)
    pg.start()

    mp = pytest.MonkeyPatch()
    mp.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", pg.admin_url)
    get_settings.cache_clear()

    command.upgrade(_alembic_config(), "head")

    engine = sa.create_engine(pg.admin_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    try:
        yield session_factory
    finally:
        engine.dispose()
        pg.stop()
        mp.undo()
        get_settings.cache_clear()


@pytest.fixture
def db_session(auth_db_sessionmaker: sessionmaker):
    """One session per test, rolled back and closed afterwards so tests
    in the same module do not see each other's uncommitted state."""
    session = auth_db_sessionmaker()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_authorization_code_guard():
    """The one-time code-exchange guard (task 4.2) is process-global
    in-memory state; reset it around every auth test so unrelated tests
    never see a stale "already consumed" code."""
    from app.auth import google

    google._consumed_codes.clear()
    yield
    google._consumed_codes.clear()
