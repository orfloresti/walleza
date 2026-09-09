"""RED -> GREEN: `0004_transfers` creates exactly the Phase 3 `app.transfer`
table, enforces its CHECK constraints, and cleanly tears down two ways —
mirroring `test_0003.py`'s exact structure and the "two teardown paths"
lesson learned during Phase 1's PR1 verify (design "Rollback Plan").

Also proves `app/transfers/models.py`'s `Transfer` ORM model round-trips
through a real `Session` against the table this migration creates
(tasks.md 1.9), and — the phase's one genuinely load-bearing empirical
claim, design D36 — proves `ON DELETE NO ACTION` (not `RESTRICT`) on both
account FKs by direct SQL: deleting an `app.account` row still referenced
by a transfer is blocked, while deleting the OWNING `app.workspace` row
succeeds and removes both the account and the transfer rows, confirming
the "checked at end-of-statement, after the workspace→transfer/account
cascades have already run" ordering claim (design RED #16).

This runs `alembic upgrade head` / `alembic downgrade` against a REAL,
ephemeral PostgreSQL server — not a mock, not SQLite — matching the exact
harness `backend/tests/migrations/test_0002.py`/`test_0003.py`
established.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import uuid
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
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-transfers-migration-test-")
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
            "No real PostgreSQL server binaries available. Provision one locally, "
            "e.g.: `conda create -y -n pgtest -c conda-forge postgresql`, or set "
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


@pytest.fixture
def migrated_db(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> Iterator[sa.Engine]:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    command.upgrade(cfg, "head")
    try:
        yield engine
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


_ALL_TABLES_AT_HEAD = {
    "app_user",
    "auth_session",
    "workspace",
    "workspace_member",
    "workspace_invite",
    "account",
    "category",
    "transaction",
    "transaction_category_split",
    "transfer",
    "alembic_version",
}


def test_head_creates_exactly_the_transfer_table(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD


def _seed_workspace_and_accounts(conn: sa.Connection) -> tuple[str, str, str]:
    workspace_row = conn.execute(
        sa.text(
            "INSERT INTO app.workspace (id, name) VALUES (gen_random_uuid(), 'W') "
            "RETURNING id"
        )
    ).first()
    assert workspace_row is not None
    from_account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'From', 'USD') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    to_account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'To', 'USD') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    conn.commit()
    assert from_account_row is not None
    assert to_account_row is not None
    return str(workspace_row.id), str(from_account_row.id), str(to_account_row.id)


def test_transfer_amount_checks_reject_zero_and_negative(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, from_account_id, to_account_id = _seed_workspace_and_accounts(conn)

        for column, other in (("from_amount", "10.00"), ("to_amount", "10.00")):
            for bad_amount in (Decimal(0), Decimal(-1)):
                amounts = {"from_amount": other, "to_amount": other}
                amounts[column] = str(bad_amount)
                violated = False
                try:
                    conn.execute(
                        sa.text(
                            "INSERT INTO app.transfer "
                            "(id, workspace_id, from_account_id, to_account_id, "
                            "from_amount, to_amount, occurred_on) "
                            "VALUES (gen_random_uuid(), :workspace_id, :from_account_id, "
                            ":to_account_id, :from_amount, :to_amount, CURRENT_DATE)"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "from_account_id": from_account_id,
                            "to_account_id": to_account_id,
                            "from_amount": amounts["from_amount"],
                            "to_amount": amounts["to_amount"],
                        },
                    )
                    conn.commit()
                except sa.exc.IntegrityError:
                    violated = True
                    conn.rollback()
                assert violated, f"transfer.{column}={bad_amount} must violate the positive CHECK"


def test_transfer_distinct_accounts_check_rejects_same_account(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, from_account_id, _to_account_id = _seed_workspace_and_accounts(conn)

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transfer "
                    "(id, workspace_id, from_account_id, to_account_id, "
                    "from_amount, to_amount, occurred_on) "
                    "VALUES (gen_random_uuid(), :workspace_id, :account_id, :account_id, "
                    "10.00, 10.00, CURRENT_DATE)"
                ),
                {"workspace_id": workspace_id, "account_id": from_account_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "from_account_id == to_account_id must violate ck_transfer_distinct_accounts"


def test_orm_model_round_trips_via_session(migrated_db: sa.Engine) -> None:
    """`Transfer` (the declarative ORM model added in this PR) can be
    inserted and queried through a real SQLAlchemy `Session` against the
    table `0004` creates — not just raw SQL through `sa.text`, mirroring
    `test_0003.py::test_orm_models_round_trip_via_session`."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.accounts.models import Account
    from app.transfers.models import Transfer
    from app.workspace.models import Workspace

    now = datetime.now(UTC)
    with Session(bind=migrated_db) as session:
        workspace = Workspace(id=uuid.uuid4(), name="Test WS", created_at=now, updated_at=now)
        session.add(workspace)
        session.flush()

        from_account = Account(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="From",
            currency="USD",
            created_at=now,
            updated_at=now,
        )
        to_account = Account(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="To",
            currency="EUR",
            created_at=now,
            updated_at=now,
        )
        session.add_all([from_account, to_account])
        session.flush()

        transfer = Transfer(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            from_amount=Decimal("100.00"),
            to_amount=Decimal("92.00"),
            occurred_on=datetime.now(UTC).date(),
            notes="ORM round trip",
            created_at=now,
            updated_at=now,
        )
        session.add(transfer)
        session.commit()

        fetched = session.query(Transfer).filter_by(id=transfer.id).one()
        assert fetched.from_amount == Decimal("100.00")
        assert fetched.to_amount == Decimal("92.00")
        assert fetched.from_account_id == from_account.id
        assert fetched.to_account_id == to_account.id
        assert fetched.notes == "ORM round trip"


# --- design D36, RED #16: NO ACTION vs RESTRICT, proved empirically ---


def test_no_action_blocks_direct_account_delete_but_workspace_cascade_removes_both(
    migrated_db: sa.Engine,
) -> None:
    """Direct SQL only — no application path deletes an `app.account` row
    (Phase 1 D6 collapsed the account lifecycle into `archived`). This is
    the phase's one genuinely load-bearing empirical claim (design D36):

    1. Deleting an `app.account` row still referenced by a transfer is
       BLOCKED — `ON DELETE NO ACTION` gives the same blocking guarantee
       `RESTRICT` would for a direct, single-table delete.
    2. Deleting the OWNING `app.workspace` row (which CASCADEs to both
       `app.account` and `app.transfer` independently) SUCCEEDS and
       removes both — proving the `NO ACTION` "checked at
       end-of-statement" semantics: by the time Postgres would check the
       transfer's FK against the now-deleted account row, the
       workspace→transfer cascade has ALREADY removed that transfer row
       too, so there is nothing left to violate the constraint. Under
       `RESTRICT` (checked immediately, mid-statement) this same
       workspace delete could error depending on unspecified
       cascade-trigger ordering — this test is the empirical proof the
       design's D36 reasoning, not just an assertion of it.
    """
    with migrated_db.connect() as conn:
        workspace_id, from_account_id, to_account_id = _seed_workspace_and_accounts(conn)

        transfer_row = conn.execute(
            sa.text(
                "INSERT INTO app.transfer "
                "(id, workspace_id, from_account_id, to_account_id, "
                "from_amount, to_amount, occurred_on) "
                "VALUES (gen_random_uuid(), :workspace_id, :from_account_id, "
                ":to_account_id, 10.00, 10.00, CURRENT_DATE) RETURNING id"
            ),
            {
                "workspace_id": workspace_id,
                "from_account_id": from_account_id,
                "to_account_id": to_account_id,
            },
        ).first()
        conn.commit()
        assert transfer_row is not None

        # Step 1: a direct delete of the referenced account is blocked.
        blocked = False
        try:
            conn.execute(
                sa.text("DELETE FROM app.account WHERE id = :id"), {"id": from_account_id}
            )
            conn.commit()
        except sa.exc.IntegrityError:
            blocked = True
            conn.rollback()
        assert blocked, (
            "deleting an app.account row still referenced by a transfer must be "
            "blocked by ON DELETE NO ACTION"
        )

        # Sanity: both rows are still there after the blocked attempt.
        remaining_accounts = conn.execute(
            sa.text("SELECT count(*) FROM app.account WHERE id = :id"),
            {"id": from_account_id},
        ).scalar_one()
        remaining_transfers = conn.execute(
            sa.text("SELECT count(*) FROM app.transfer WHERE id = :id"),
            {"id": transfer_row.id},
        ).scalar_one()
        assert remaining_accounts == 1
        assert remaining_transfers == 1

        # Step 2: deleting the OWNING workspace succeeds and removes both
        # the accounts and the transfer — the end-of-statement ordering
        # claim this whole test exists to prove.
        conn.execute(sa.text("DELETE FROM app.workspace WHERE id = :id"), {"id": workspace_id})
        conn.commit()

        accounts_after = conn.execute(
            sa.text("SELECT count(*) FROM app.account WHERE workspace_id = :id"),
            {"id": workspace_id},
        ).scalar_one()
        transfers_after = conn.execute(
            sa.text("SELECT count(*) FROM app.transfer WHERE workspace_id = :id"),
            {"id": workspace_id},
        ).scalar_one()
        assert accounts_after == 0
        assert transfers_after == 0


def test_downgrade_one_step_drops_only_the_transfer_table(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            workspace_id, from_account_id, to_account_id = _seed_workspace_and_accounts(conn)
            conn.execute(
                sa.text(
                    "INSERT INTO app.transfer "
                    "(id, workspace_id, from_account_id, to_account_id, "
                    "from_amount, to_amount, occurred_on) "
                    "VALUES (gen_random_uuid(), :workspace_id, :from_account_id, "
                    ":to_account_id, 10.00, 10.00, CURRENT_DATE)"
                ),
                {
                    "workspace_id": workspace_id,
                    "from_account_id": from_account_id,
                    "to_account_id": to_account_id,
                },
            )
            conn.commit()

        command.downgrade(cfg, "-1")

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names(schema="app")) == {
            "app_user",
            "auth_session",
            "workspace",
            "workspace_member",
            "workspace_invite",
            "account",
            "category",
            "transaction",
            "transaction_category_split",
            "alembic_version",
        }

        with engine.connect() as conn:
            remaining_accounts = conn.execute(
                sa.text("SELECT count(*) FROM app.account WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalar()
        assert remaining_accounts == 2

        command.upgrade(cfg, "head")
        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_base_drops_every_product_table_including_transfer(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD

        command.downgrade(cfg, "base")

        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == {"alembic_version"}

        command.upgrade(cfg, "head")
        inspector_replayed = sa.inspect(engine)
        assert set(inspector_replayed.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
