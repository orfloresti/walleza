"""RED -> GREEN: `0007_workspace_roles` adds `app.workspace_member.role`
with its CHECK constraint, and its 3-step backfill (design D94, spec
workspace-roles domain "Role Column and Backfill" requirement):

1. The membership row matching `Workspace.created_by_user_id` becomes
   `owner`.
2. Fallback: the earliest-`joined_at` member becomes `owner` for any
   workspace still without one.
3. Every workspace must end with exactly one owner, or `upgrade()` raises
   `RuntimeError` and the whole migration rolls back.

Follows the exact real-Postgres harness `test_0002.py` established
(`initdb`/`pg_ctl`, not Docker/testcontainers — see that module's
docstring for why).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

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
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-test-0007-")
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
            "access in this sandbox and no `initdb`/`pg_ctl` on PATH. "
            "Provision one locally, e.g.: "
            "`conda create -y -n pgtest -c conda-forge postgresql`, or set "
            "WALLEZA_TEST_PG_BIN_DIR. See backend/README.md 'Testing migrations'."
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


def _seed_workspace(
    conn: sa.Connection, *, created_by_user_id: str | None
) -> str:
    row = conn.execute(
        sa.text(
            "INSERT INTO app.workspace (id, name, created_by_user_id) "
            "VALUES (gen_random_uuid(), 'W', :creator) RETURNING id"
        ),
        {"creator": created_by_user_id},
    ).first()
    assert row is not None
    return str(row.id)


def _seed_user(conn: sa.Connection, *, email: str) -> str:
    row = conn.execute(
        sa.text(
            "INSERT INTO app.app_user (id, google_sub, email) "
            "VALUES (gen_random_uuid(), :sub, :email) RETURNING id"
        ),
        {"sub": f"sub-{uuid.uuid4()}", "email": email},
    ).first()
    assert row is not None
    return str(row.id)


def _seed_member(
    conn: sa.Connection, *, workspace_id: str, user_id: str, joined_at_offset_seconds: int = 0
) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO app.workspace_member (id, workspace_id, user_id, joined_at) "
            "VALUES (gen_random_uuid(), :wsid, :uid, "
            "now() + (:offset || ' seconds')::interval)"
        ),
        {"wsid": workspace_id, "uid": user_id, "offset": joined_at_offset_seconds},
    )


def test_creator_backfilled_as_owner(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0006")

        with engine.begin() as conn:
            creator_id = _seed_user(conn, email="creator@example.com")
            peer_id = _seed_user(conn, email="peer@example.com")
            workspace_id = _seed_workspace(conn, created_by_user_id=creator_id)
            _seed_member(conn, workspace_id=workspace_id, user_id=creator_id)
            _seed_member(conn, workspace_id=workspace_id, user_id=peer_id, joined_at_offset_seconds=5)

        command.upgrade(cfg, "0007")

        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT user_id, role FROM app.workspace_member WHERE workspace_id = :wsid"
                ),
                {"wsid": workspace_id},
            ).all()
        roles = {str(r.user_id): r.role for r in rows}
        assert roles[creator_id] == "owner"
        assert roles[peer_id] == "member"
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_fallback_to_earliest_member_when_creator_has_no_row(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0006")

        with engine.begin() as conn:
            # created_by_user_id is NULL (creator's own app_user row is
            # gone, matching its ON DELETE SET NULL semantics) — nobody
            # matches step 1, so step 2 must promote the earliest joiner.
            workspace_id = _seed_workspace(conn, created_by_user_id=None)
            earliest_id = _seed_user(conn, email="earliest@example.com")
            later_id = _seed_user(conn, email="later@example.com")
            _seed_member(
                conn, workspace_id=workspace_id, user_id=earliest_id, joined_at_offset_seconds=0
            )
            _seed_member(
                conn, workspace_id=workspace_id, user_id=later_id, joined_at_offset_seconds=10
            )

        command.upgrade(cfg, "0007")

        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT user_id, role FROM app.workspace_member WHERE workspace_id = :wsid"
                ),
                {"wsid": workspace_id},
            ).all()
        roles = {str(r.user_id): r.role for r in rows}
        assert roles[earliest_id] == "owner"
        assert roles[later_id] == "member"
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_zero_owner_workspace_blocks_upgrade(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workspace with ZERO member rows cannot be fixed by step 2 (there
    is nobody to promote) and must abort the whole migration with
    `RuntimeError`, rolling the transaction back rather than leaving the
    schema half-migrated."""
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0006")

        with engine.begin() as conn:
            _seed_workspace(conn, created_by_user_id=None)  # zero members, ever

        with pytest.raises(RuntimeError, match="exactly one owner"):
            command.upgrade(cfg, "0007")

        inspector = sa.inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("workspace_member", schema="app")}
        assert "role" not in columns, (
            "a failed upgrade must roll back entirely — the role column must not persist"
        )
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_role_check_constraint_rejects_invalid_value(
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
            creator_id = _seed_user(conn, email="ck-creator@example.com")
            workspace_id = _seed_workspace(conn, created_by_user_id=creator_id)

        violated = False
        try:
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.workspace_member (id, workspace_id, user_id, role) "
                        "VALUES (gen_random_uuid(), :wsid, :uid, 'superadmin')"
                    ),
                    {"wsid": workspace_id, "uid": creator_id},
                )
        except sa.exc.IntegrityError:
            violated = True
        assert violated, "role='superadmin' must violate ck_workspace_member_role"
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_drops_role_column_only(
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
            creator_id = _seed_user(conn, email="downgrade-creator@example.com")
            _seed_workspace(conn, created_by_user_id=creator_id)

        command.downgrade(cfg, "0006")

        inspector = sa.inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("workspace_member", schema="app")}
        assert "role" not in columns

        with engine.connect() as conn:
            remaining_users = conn.execute(sa.text("SELECT count(*) FROM app.app_user")).scalar()
        assert remaining_users == 1
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
