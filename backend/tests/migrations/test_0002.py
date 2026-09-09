"""RED -> GREEN: `0002_workspace_accounts` creates exactly the four Phase 1
product-domain tables (`app.workspace`, `app.workspace_member`,
`app.workspace_invite`, `app.account`), enforces the `account` CHECK
constraints, and `alembic downgrade -1` cleanly removes exactly those four
tables while leaving `0001`'s auth tables (`app.app_user`,
`app.auth_session`) completely untouched (spec RED #10; tasks 1.1/1.6).

Also proves the `app/workspace/models.py` / `app/accounts/models.py` ORM
layer actually round-trips through a real `Session` against these
migration-created tables (tasks 1.3/1.4). This caught a real bug during
development: a `ForeignKey("app.app_user.id", ...)` on a model declared
against `app.db.Base` cannot be resolved by the ORM's flush-time table
sort unless `app_user` is ALSO registered (even as a minimal stub) on that
same `Base.metadata` — seeing the confirmed happy-path insert succeed here
is the regression guard for that fix (see `app/db.py`'s `_app_user_ref`).

This runs `alembic upgrade head` / `alembic downgrade -1` against a REAL,
ephemeral PostgreSQL server — not a mock, not SQLite — matching the exact
harness `backend/tests/migrations/test_baseline.py` established for
`0001_baseline` (design's stated testing strategy: "Alembic upgrade head
then downgrade base on a throwaway Postgres"; this module downgrades one
step instead of to `base`, since it must prove `0001`'s tables survive).

Docker is not usable in this sandbox (the docker daemon socket exists but
this user has no `docker` group membership and there is no passwordless
sudo), so this test starts a real PostgreSQL cluster directly from server
binaries (`initdb`/`pg_ctl`) instead of testcontainers, exactly as
`test_baseline.py` does. It looks for those binaries on `PATH` first, then
falls back to a dedicated conda environment. If neither is available it
skips with a clear message rather than silently passing — see
`backend/README.md` "Testing migrations" for how to provision them.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from decimal import Decimal
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


@pytest.fixture
def migrated_db(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sa.Engine]:
    """Pinned to the explicit "0002" revision rather than "head", on the
    shared ephemeral server, torn back down to `base` after each test so
    tests in this module don't leak state into one another (the server
    itself is reused module-wide per `real_postgres`).

    Pinned rather than "head" for the same reason
    `test_baseline.py::test_baseline_creates_only_auth_tables_and_downgrades_cleanly`
    pins to "0001": once `0003_categories_transactions` (Phase 2) exists,
    "head" resolves past this revision, and this module's tests assert the
    EXACT table set `0002` alone defines — not whatever the latest
    revision happens to add.
    """
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    command.upgrade(cfg, "0002")
    try:
        yield engine
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_head_creates_exactly_the_four_new_tables(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    assert set(inspector.get_table_names(schema="app")) == {
        "app_user",
        "auth_session",
        "workspace",
        "workspace_member",
        "workspace_invite",
        "account",
        "alembic_version",
    }


def test_currency_check_rejects_lowercase_and_wrong_length(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _user_id = _seed_workspace_and_user(conn)

        for bad_currency in ("us", "USDX"):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.account "
                        "(id, workspace_id, name, currency) "
                        "VALUES (gen_random_uuid(), :workspace_id, 'a', :currency)"
                    ),
                    {"workspace_id": workspace_id, "currency": bad_currency},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"currency={bad_currency!r} must violate the ISO 4217 CHECK"


def test_exchange_rate_check_rejects_zero_and_negative(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _user_id = _seed_workspace_and_user(conn)

        for bad_rate in (Decimal(0), Decimal(-1)):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.account "
                        "(id, workspace_id, name, currency, exchange_rate) "
                        "VALUES (gen_random_uuid(), :workspace_id, 'a', 'USD', :rate)"
                    ),
                    {"workspace_id": workspace_id, "rate": bad_rate},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"exchange_rate={bad_rate} must violate the positive-rate CHECK"


def test_personal_account_requires_owner(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, user_id = _seed_workspace_and_user(conn)

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.account "
                    "(id, workspace_id, name, currency, is_personal, owner_user_id) "
                    "VALUES (gen_random_uuid(), :workspace_id, 'a', 'USD', true, NULL)"
                ),
                {"workspace_id": workspace_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "a personal account with NULL owner_user_id must violate the CHECK"

        # Sanity: the same insert succeeds once an owner is supplied.
        conn.execute(
            sa.text(
                "INSERT INTO app.account "
                "(id, workspace_id, name, currency, is_personal, owner_user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, 'a', 'USD', true, :owner)"
            ),
            {"workspace_id": workspace_id, "owner": user_id},
        )
        conn.commit()


def test_orm_models_round_trip_via_session(migrated_db: sa.Engine) -> None:
    """`Workspace`/`WorkspaceMember`/`WorkspaceInvite`/`Account` (the
    declarative ORM models added in this PR) can be inserted and queried
    through a real SQLAlchemy `Session` against the tables `0002` creates —
    not just raw SQL through `sa.text`, as the other tests in this module
    use for constraint probing."""
    import uuid
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session

    from app.accounts.models import Account
    from app.workspace.models import Workspace, WorkspaceInvite, WorkspaceMember

    now = datetime.now(UTC)
    with Session(bind=migrated_db) as session:
        workspace = Workspace(id=uuid.uuid4(), name="Test WS", created_at=now, updated_at=now)
        session.add(workspace)
        session.flush()

        user_id = uuid.uuid4()
        session.execute(
            sa.text(
                "INSERT INTO app.app_user (id, google_sub, email, created_at, updated_at) "
                "VALUES (:id, 'sub-orm', 'orm@example.com', now(), now())"
            ),
            {"id": user_id},
        )

        member = WorkspaceMember(
            id=uuid.uuid4(), workspace_id=workspace.id, user_id=user_id, joined_at=now
        )
        session.add(member)

        invite = WorkspaceInvite(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            created_by_user_id=user_id,
            token_hash="orm-test-hash",
            expires_at=now,
            created_at=now,
        )
        session.add(invite)

        account = Account(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            owner_user_id=user_id,
            name="Personal",
            currency="USD",
            exchange_rate=Decimal(1),
            initial_funds=Decimal("100.00"),
            is_personal=True,
            archived=False,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.commit()

        fetched_account = session.query(Account).filter_by(workspace_id=workspace.id).one()
        assert fetched_account.currency == "USD"
        assert fetched_account.initial_funds == Decimal("100.00")
        assert fetched_account.is_personal is True

        fetched_member = session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).one()
        assert fetched_member.user_id == user_id

        fetched_invite = session.query(WorkspaceInvite).filter_by(workspace_id=workspace.id).one()
        assert fetched_invite.token_hash == "orm-test-hash"


def test_workspace_member_user_id_is_unique(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, user_id = _seed_workspace_and_user(conn)
        conn.execute(
            sa.text(
                "INSERT INTO app.workspace_member (id, workspace_id, user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, :user_id)"
            ),
            {"workspace_id": workspace_id, "user_id": user_id},
        )
        conn.commit()

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.workspace_member (id, workspace_id, user_id) "
                    "VALUES (gen_random_uuid(), :workspace_id, :user_id)"
                ),
                {"workspace_id": workspace_id, "user_id": user_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "a second workspace_member row for the same user_id must be rejected"


def _seed_workspace_and_user(conn: sa.Connection) -> tuple[str, str]:
    workspace_row = conn.execute(
        sa.text(
            "INSERT INTO app.workspace (id, name) VALUES (gen_random_uuid(), 'W') "
            "RETURNING id"
        )
    ).first()
    user_row = conn.execute(
        sa.text(
            "INSERT INTO app.app_user (id, google_sub, email) "
            "VALUES (gen_random_uuid(), 'sub-1', 'a@example.com') RETURNING id"
        )
    ).first()
    conn.commit()
    assert workspace_row is not None
    assert user_row is not None
    return str(workspace_row.id), str(user_row.id)


def test_downgrade_one_step_drops_only_the_four_new_tables(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned to "0002" rather than "head" (see `migrated_db`'s docstring
    above): once `0003_categories_transactions` exists, "head" resolves
    past this revision and both the pre-/post-downgrade table-set
    assertions below are specifically about `0002` in isolation."""
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0002")

        with engine.connect() as conn:
            _workspace_id, user_id = _seed_workspace_and_user(conn)
            conn.execute(
                sa.text(
                    "INSERT INTO app.auth_session "
                    "(id, user_id, refresh_hash, family_id, expires_at) "
                    "VALUES (gen_random_uuid(), :user_id, 'x', gen_random_uuid(), "
                    "now() + interval '1 day')"
                ),
                {"user_id": user_id},
            )
            conn.commit()

        # downgrade -1 must drop exactly the four Phase 1 tables and leave
        # 0001's app_user/auth_session tables, and their rows, intact.
        command.downgrade(cfg, "-1")

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names(schema="app")) == {
            "app_user",
            "auth_session",
            "alembic_version",
        }

        with engine.connect() as conn:
            remaining_users = conn.execute(sa.text("SELECT count(*) FROM app.app_user")).scalar()
            remaining_sessions = conn.execute(
                sa.text("SELECT count(*) FROM app.auth_session")
            ).scalar()
        assert remaining_users == 1
        assert remaining_sessions == 1

        # Re-upgrading to 0002 after a -1 downgrade must succeed cleanly too.
        command.upgrade(cfg, "0002")
        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == {
            "app_user",
            "auth_session",
            "workspace",
            "workspace_member",
            "workspace_invite",
            "account",
            "alembic_version",
        }
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
