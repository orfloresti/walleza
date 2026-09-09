"""Shared fixtures for `app/categories` tests.

Duplicates the same `_EphemeralPostgres` harness already established in
`tests/migrations/test_0002.py`, `tests/auth/conftest.py`,
`tests/workspace/conftest.py`, and `tests/accounts/conftest.py` —
self-contained per test area, matching Phase 1/PR1's established
precedent.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"

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
    def __init__(self, bin_dir: str) -> None:
        self.bin_dir = bin_dir
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-categories-test-")
        self.port = _free_tcp_port()
        self.log_path = os.path.join(self.data_dir, "server.log")

    def _run(self, executable: str, *args: str) -> None:
        exe = os.path.join(self.bin_dir, executable)
        subprocess.run([exe, *args], check=True, capture_output=True, text=True)

    def start(self) -> None:
        self._run(
            "initdb", "-D", self.data_dir, "-U", "postgres", "-A", "trust",
            "--no-sync", "--encoding=UTF8",
        )
        self._run(
            "pg_ctl", "-D", self.data_dir, "-l", self.log_path, "-w", "-o",
            f"-p {self.port} -k {self.data_dir} -c listen_addresses=127.0.0.1", "start",
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
def categories_db_sessionmaker() -> Iterator[sessionmaker]:
    bin_dir = _find_pg_bin_dir()
    if not bin_dir:
        pytest.skip(
            "No real PostgreSQL server binaries available. Provision one locally, "
            "e.g.: `conda create -y -n pgtest -c conda-forge postgresql`, or set "
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
def db_session(categories_db_sessionmaker: sessionmaker):
    """One session per test, committed and closed afterwards. Tests use
    this for out-of-band seeding/assertions (raw SQL); the app itself gets
    its OWN fresh session per request via `app_factory`'s dependency
    override — exactly matching `tests/accounts/conftest.py`'s pattern."""
    session = categories_db_sessionmaker()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture
def seed_user(db_session) -> Callable[..., uuid.UUID]:
    """Factory fixture: `seed_user(email="a@example.com")` inserts a
    minimal `app.app_user` row directly (Phase 2 does not touch signup —
    Phase 0 owns that) and returns its id."""

    def _seed(*, email: str) -> uuid.UUID:
        user_id = uuid.uuid4()
        db_session.execute(
            sa.text(
                "INSERT INTO app.app_user (id, google_sub, email, created_at, updated_at) "
                "VALUES (:id, :sub, :email, now(), now())"
            ),
            {"id": user_id, "sub": f"sub-{user_id}", "email": email},
        )
        db_session.commit()
        return user_id

    return _seed


@pytest.fixture
def app_factory(categories_db_sessionmaker: sessionmaker) -> Callable[[], object]:
    """Factory fixture: `app_factory()` returns a fresh `FastAPI` app whose
    `get_db` dependency is overridden to hand out sessions bound to the
    SAME real ephemeral Postgres `categories_db_sessionmaker` uses — so
    out-of-band seeding via `seed_user`/`db_session` and in-app requests
    see the same committed rows, exactly as two different processes
    talking to the same real database would."""

    def _make():
        app = create_app()

        def override_get_db():
            session = categories_db_sessionmaker()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        return app

    return _make
