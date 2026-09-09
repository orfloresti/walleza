"""RED -> GREEN: `0003_categories_transactions` creates exactly the three
Phase 2 product-domain tables (`app.category`, `app.transaction`,
`app.transaction_category_split`), enforces their CHECK constraints and
FKs, and cleanly tears down two ways:

- `alembic downgrade -1` removes exactly those three tables while leaving
  every `0001`/`0002` table (`app.app_user`, `app.auth_session`,
  `app.workspace`, `app.workspace_member`, `app.workspace_invite`,
  `app.account`) — and their rows — completely untouched.
- `alembic downgrade base` removes ALL product-domain tables, back down
  to just Alembic's own `alembic_version` bookkeeping table.

Both teardown paths are asserted explicitly and independently in this
module (`test_downgrade_one_step_...` and `test_downgrade_base_...`)
rather than relying on only one of them — a lesson learned during Phase
1's PR1 verify, where a single teardown path left a rollback assumption
unverified (spec/tasks 1.6, design "Rollback Plan").

Also proves the `app/categories/models.py` / `app/transactions/models.py`
ORM layer actually round-trips through a real `Session` against these
migration-created tables (tasks 1.2-1.4), mirroring
`test_0002.py::test_orm_models_round_trip_via_session`.

This runs `alembic upgrade head` / `alembic downgrade` against a REAL,
ephemeral PostgreSQL server — not a mock, not SQLite — matching the exact
harness `backend/tests/migrations/test_0002.py` established. Docker is
not usable in this sandbox (the docker daemon socket exists but this user
has no `docker` group membership and there is no passwordless sudo), so
this test starts a real PostgreSQL cluster directly from server binaries
(`initdb`/`pg_ctl`) instead of testcontainers. It looks for those
binaries on `PATH` first, then falls back to a dedicated conda
environment. If neither is available it skips with a clear message
rather than silently passing — see `backend/README.md` "Testing
migrations" for how to provision them.
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
    """Upgrade to exactly `0003` (this module's own revision, NOT literal
    Alembic `head`) on the shared ephemeral server, torn back down to
    `base` after each test so tests in this module don't leak state into
    one another (the server itself is reused module-wide per
    `real_postgres`).

    Pinned to `"0003"` rather than `"head"` — matching
    `test_0002.py`'s own established precedent — so this module keeps
    testing exactly the guarantees `0003_categories_transactions` makes,
    independent of how many later revisions (`0004_transfers` onward) get
    chained after it. The original `"head"` literal here was a latent gap
    surfaced (not introduced) by Phase 3 adding `0004`: this migration's
    own `_ALL_TABLES_AT_HEAD` name is a historical label from when `0003`
    WAS head; it means "the tables that exist once `0003` is applied"."""
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    command.upgrade(cfg, "0003")
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
    "alembic_version",
}


def test_head_creates_exactly_the_three_new_tables(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD


def _seed_workspace_account_and_user(conn: sa.Connection) -> tuple[str, str, str]:
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
    assert workspace_row is not None
    assert user_row is not None
    account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Checking', 'USD') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    conn.commit()
    assert account_row is not None
    return str(workspace_row.id), str(account_row.id), str(user_row.id)


def test_category_type_check_rejects_transfer_and_invalid(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, _user_id = _seed_workspace_account_and_user(conn)

        for bad_type in ("transfer", "TRANSFER", "", "expenses"):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.category (id, workspace_id, name, type) "
                        "VALUES (gen_random_uuid(), :workspace_id, 'Food', :type)"
                    ),
                    {"workspace_id": workspace_id, "type": bad_type},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"category.type={bad_type!r} must violate the CHECK"


def test_category_no_self_parent_check(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, _user_id = _seed_workspace_account_and_user(conn)

        new_id_row = conn.execute(sa.text("SELECT gen_random_uuid() AS id")).first()
        assert new_id_row is not None
        new_id = new_id_row.id

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.category (id, workspace_id, parent_id, name, type) "
                    "VALUES (:id, :workspace_id, :id, 'Loop', 'expense')"
                ),
                {"id": new_id, "workspace_id": workspace_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "a category whose parent_id equals its own id must violate the CHECK"


def test_category_parent_restrict_blocks_deletion_while_children_exist(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, _user_id = _seed_workspace_account_and_user(conn)

        parent_row = conn.execute(
            sa.text(
                "INSERT INTO app.category (id, workspace_id, name, type) "
                "VALUES (gen_random_uuid(), :workspace_id, 'Parent', 'expense') RETURNING id"
            ),
            {"workspace_id": workspace_id},
        ).first()
        assert parent_row is not None
        conn.execute(
            sa.text(
                "INSERT INTO app.category (id, workspace_id, parent_id, name, type) "
                "VALUES (gen_random_uuid(), :workspace_id, :parent_id, 'Child', 'expense')"
            ),
            {"workspace_id": workspace_id, "parent_id": parent_row.id},
        )
        conn.commit()

        violated = False
        try:
            conn.execute(
                sa.text("DELETE FROM app.category WHERE id = :id"), {"id": parent_row.id}
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "deleting a parent category with children must be RESTRICTed by the FK"


def test_transaction_type_check_rejects_transfer(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _user_id = _seed_workspace_account_and_user(conn)

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on) "
                    "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'transfer', "
                    "10.00, CURRENT_DATE)"
                ),
                {"workspace_id": workspace_id, "account_id": account_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "transaction.type='transfer' must violate the CHECK (decision 8)"


def test_transaction_amount_check_rejects_zero_and_negative(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _user_id = _seed_workspace_account_and_user(conn)

        for bad_amount in (Decimal(0), Decimal(-1)):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.transaction "
                        "(id, workspace_id, account_id, type, amount, occurred_on) "
                        "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                        ":amount, CURRENT_DATE)"
                    ),
                    {"workspace_id": workspace_id, "account_id": account_id, "amount": bad_amount},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"transaction.amount={bad_amount} must violate the positive CHECK"


def test_transaction_photo_pair_check(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _user_id = _seed_workspace_account_and_user(conn)

        # content_type set but uploaded_at NULL must violate the CHECK.
        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on, "
                    "photo_content_type, photo_uploaded_at) "
                    "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                    "10.00, CURRENT_DATE, 'image/jpeg', NULL)"
                ),
                {"workspace_id": workspace_id, "account_id": account_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "photo_content_type set with NULL photo_uploaded_at must violate CHECK"

        # uploaded_at set but content_type NULL must also violate the CHECK.
        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on, "
                    "photo_content_type, photo_uploaded_at) "
                    "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                    "10.00, CURRENT_DATE, NULL, now())"
                ),
                {"workspace_id": workspace_id, "account_id": account_id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "photo_uploaded_at set with NULL photo_content_type must violate CHECK"

        # Both NULL (no photo) and both set (photo present) are legal.
        conn.execute(
            sa.text(
                "INSERT INTO app.transaction "
                "(id, workspace_id, account_id, type, amount, occurred_on) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                "10.00, CURRENT_DATE)"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO app.transaction "
                "(id, workspace_id, account_id, type, amount, occurred_on, "
                "photo_content_type, photo_uploaded_at) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                "10.00, CURRENT_DATE, 'image/png', now())"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )
        conn.commit()


def test_split_amount_check_and_unique_constraint(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _user_id = _seed_workspace_account_and_user(conn)

        txn_row = conn.execute(
            sa.text(
                "INSERT INTO app.transaction "
                "(id, workspace_id, account_id, type, amount, occurred_on) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                "100.00, CURRENT_DATE) RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        ).first()
        category_row = conn.execute(
            sa.text(
                "INSERT INTO app.category (id, workspace_id, name, type) "
                "VALUES (gen_random_uuid(), :workspace_id, 'Food', 'expense') RETURNING id"
            ),
            {"workspace_id": workspace_id},
        ).first()
        conn.commit()
        assert txn_row is not None
        assert category_row is not None

        # amount <= 0 violates the CHECK.
        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_category_split "
                    "(id, transaction_id, category_id, amount) "
                    "VALUES (gen_random_uuid(), :txn_id, :category_id, 0)"
                ),
                {"txn_id": txn_row.id, "category_id": category_row.id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "transaction_category_split.amount=0 must violate the positive CHECK"

        # A legal split line persists.
        conn.execute(
            sa.text(
                "INSERT INTO app.transaction_category_split "
                "(id, transaction_id, category_id, amount) "
                "VALUES (gen_random_uuid(), :txn_id, :category_id, 100.00)"
            ),
            {"txn_id": txn_row.id, "category_id": category_row.id},
        )
        conn.commit()

        # A second split line for the SAME (transaction_id, category_id)
        # pair violates the UNIQUE constraint.
        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_category_split "
                    "(id, transaction_id, category_id, amount) "
                    "VALUES (gen_random_uuid(), :txn_id, :category_id, 1.00)"
                ),
                {"txn_id": txn_row.id, "category_id": category_row.id},
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "a duplicate (transaction_id, category_id) split must violate UNIQUE"


def test_orm_models_round_trip_via_session(migrated_db: sa.Engine) -> None:
    """`Category`/`Transaction`/`TransactionCategorySplit` (the declarative
    ORM models added in this PR) can be inserted and queried through a real
    SQLAlchemy `Session` against the tables `0003` creates — not just raw
    SQL through `sa.text`, mirroring
    `test_0002.py::test_orm_models_round_trip_via_session`."""
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.accounts.models import Account
    from app.categories.models import Category
    from app.transactions.models import Transaction, TransactionCategorySplit
    from app.workspace.models import Workspace

    now = datetime.now(UTC)
    with Session(bind=migrated_db) as session:
        workspace = Workspace(id=uuid.uuid4(), name="Test WS", created_at=now, updated_at=now)
        session.add(workspace)
        session.flush()

        account = Account(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="Checking",
            currency="USD",
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        session.flush()

        parent_category = Category(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="Food",
            type="expense",
            created_at=now,
            updated_at=now,
        )
        session.add(parent_category)
        session.flush()

        child_category = Category(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            parent_id=parent_category.id,
            name="Groceries",
            icon="cart",
            type="expense",
            created_at=now,
            updated_at=now,
        )
        session.add(child_category)
        session.flush()

        transaction = Transaction(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            account_id=account.id,
            type="expense",
            amount=Decimal("100.00"),
            occurred_on=datetime.now(UTC).date(),
            notes="weekly groceries",
            is_refund=False,
            checked=True,
            created_at=now,
            updated_at=now,
        )
        session.add(transaction)
        session.flush()

        split = TransactionCategorySplit(
            id=uuid.uuid4(),
            transaction_id=transaction.id,
            category_id=child_category.id,
            amount=Decimal("100.00"),
        )
        session.add(split)
        session.commit()

        fetched_txn = session.query(Transaction).filter_by(id=transaction.id).one()
        assert fetched_txn.amount == Decimal("100.00")
        assert fetched_txn.type == "expense"
        assert fetched_txn.checked is True

        fetched_split = (
            session.query(TransactionCategorySplit)
            .filter_by(transaction_id=transaction.id)
            .one()
        )
        assert fetched_split.category_id == child_category.id
        assert fetched_split.amount == Decimal("100.00")

        fetched_child = session.query(Category).filter_by(id=child_category.id).one()
        assert fetched_child.parent_id == parent_category.id
        assert fetched_child.icon == "cart"


def test_downgrade_one_step_drops_only_the_three_new_tables(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`alembic downgrade -1` from `0003` must drop exactly `category`,
    `transaction`, and `transaction_category_split`, leaving every
    `0001`/`0002` table (and its rows) intact — the FIRST of the two
    explicitly-tested teardown paths (design "Rollback Plan"). Pinned to
    `"0003"` rather than literal `"head"` — see `migrated_db`'s docstring
    above for why."""
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0003")

        with engine.connect() as conn:
            workspace_id, _account_id, _user_id = _seed_workspace_account_and_user(conn)
            conn.execute(
                sa.text(
                    "INSERT INTO app.account (id, workspace_id, name, currency) "
                    "VALUES (gen_random_uuid(), :workspace_id, 'Savings', 'USD')"
                ),
                {"workspace_id": workspace_id},
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
            "alembic_version",
        }

        with engine.connect() as conn:
            remaining_accounts = conn.execute(
                sa.text("SELECT count(*) FROM app.account WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalar()
        assert remaining_accounts == 2

        # Re-upgrading to 0003 after a -1 downgrade must succeed cleanly too.
        command.upgrade(cfg, "0003")
        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_base_drops_every_product_table(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`alembic downgrade base` from `0003` must remove ALL product-domain
    tables across `0001`/`0002`/`0003` — the SECOND of the two
    explicitly-tested teardown paths (design "Rollback Plan"), distinct
    from the single-step `-1` case above: this proves the full chain
    tears down cleanly, not just this revision's own three tables. Pinned
    to `"0003"` rather than literal `"head"` — see `migrated_db`'s
    docstring above for why."""
    from app.config import get_settings

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()

    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "0003")

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD

        command.downgrade(cfg, "base")

        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == {"alembic_version"}

        # Re-upgrading to 0003 after a full `base` downgrade must succeed
        # cleanly too, proving the chain is replayable in both directions.
        command.upgrade(cfg, "0003")
        inspector_replayed = sa.inspect(engine)
        assert set(inspector_replayed.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
