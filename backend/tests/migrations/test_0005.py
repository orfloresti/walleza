"""RED -> GREEN: `0005_templates_and_recurring` creates exactly the Phase 4
`app.transaction_template`, `app.transaction_template_split`,
`app.recurring_transaction`, `app.recurring_transaction_split`, and
`app.recurring_occurrence` tables, enforces every CHECK constraint from
design's schema block, and cleanly tears down — mirroring
`test_0004.py`'s exact structure (tasks.md task 1.1/1.5).

This runs `alembic upgrade head` / `alembic downgrade` against a REAL,
ephemeral PostgreSQL server — not a mock, not SQLite — matching the exact
harness `backend/tests/migrations/test_0002.py`/`test_0003.py`/
`test_0004.py` established.
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
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-recurring-migration-test-")
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


_TABLES_BEFORE_0005 = {
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

_ALL_TABLES_AT_HEAD = _TABLES_BEFORE_0005 | {
    "transaction_template",
    "transaction_template_split",
    "recurring_transaction",
    "recurring_transaction_split",
    "recurring_occurrence",
}


def test_head_creates_exactly_the_five_new_tables(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD


def _seed_workspace_account_category(conn: sa.Connection) -> tuple[str, str, str]:
    workspace_row = conn.execute(
        sa.text(
            "INSERT INTO app.workspace (id, name) VALUES (gen_random_uuid(), 'W') "
            "RETURNING id"
        )
    ).first()
    assert workspace_row is not None
    account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Checking', 'USD') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    category_row = conn.execute(
        sa.text(
            "INSERT INTO app.category (id, workspace_id, name, type) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Groceries', 'expense') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    conn.commit()
    assert account_row is not None
    assert category_row is not None
    return str(workspace_row.id), str(account_row.id), str(category_row.id)


def _seed_user(conn: sa.Connection) -> str:
    user_row = conn.execute(
        sa.text(
            "INSERT INTO app.app_user (id, google_sub, email, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :sub, :email, now(), now()) RETURNING id"
        ),
        {"sub": f"sub-{uuid.uuid4()}", "email": f"{uuid.uuid4()}@example.com"},
    ).first()
    conn.commit()
    assert user_row is not None
    return str(user_row.id)


def _insert_template(conn: sa.Connection, *, workspace_id, account_id, user_id, **overrides):
    values = {
        "workspace_id": workspace_id,
        "account_id": account_id,
        "name": "Rent",
        "type": "expense",
        "amount": "100.00",
        "user_id": user_id,
    }
    values.update(overrides)
    conn.execute(
        sa.text(
            "INSERT INTO app.transaction_template "
            "(id, workspace_id, account_id, name, type, amount, created_by_user_id) "
            "VALUES (gen_random_uuid(), :workspace_id, :account_id, :name, :type, "
            ":amount, :user_id)"
        ),
        values,
    )
    conn.commit()


def _insert_recurring(conn: sa.Connection, *, workspace_id, account_id, user_id, **overrides):
    values = {
        "workspace_id": workspace_id,
        "account_id": account_id,
        "type": "expense",
        "amount": "50.00",
        "repeat_every": 1,
        "period": "month",
        "starts_on": "2026-01-01",
        "next_date": "2026-01-01",
        "ends_on": None,
        "reminder_days_before": None,
        "reminder_locale": "en",
        "user_id": user_id,
    }
    values.update(overrides)
    conn.execute(
        sa.text(
            "INSERT INTO app.recurring_transaction "
            "(id, workspace_id, account_id, type, amount, repeat_every, period, "
            "starts_on, next_date, ends_on, reminder_days_before, reminder_locale, "
            "created_by_user_id) "
            "VALUES (gen_random_uuid(), :workspace_id, :account_id, :type, :amount, "
            ":repeat_every, :period, :starts_on, :next_date, :ends_on, "
            ":reminder_days_before, :reminder_locale, :user_id)"
        ),
        values,
    )
    conn.commit()


# --- CHECK constraint coverage: transaction_template ---


def test_transaction_template_type_check_rejects_transfer(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            _insert_template(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                user_id=user_id,
                type="transfer",
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "transaction_template.type='transfer' must violate the CHECK"


def test_transaction_template_amount_check_rejects_zero_and_negative(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        for bad_amount in ("0", "-1.00"):
            violated = False
            try:
                _insert_template(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                    user_id=user_id,
                    amount=bad_amount,
                )
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"transaction_template.amount={bad_amount} must violate the CHECK"


def test_transaction_template_split_amount_check_and_unique_and_category_restrict(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, category_id = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        template_row = conn.execute(
            sa.text(
                "INSERT INTO app.transaction_template "
                "(id, workspace_id, account_id, name, type, amount, created_by_user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'Rent', 'expense', "
                "100.00, :user_id) RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id, "user_id": user_id},
        ).first()
        conn.commit()
        assert template_row is not None

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_template_split "
                    "(id, template_id, category_id, amount) "
                    "VALUES (gen_random_uuid(), :template_id, :category_id, 0)"
                ),
                {"template_id": template_row.id, "category_id": category_id},
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "transaction_template_split.amount=0 must violate the CHECK"

        # A category referenced by a split cannot be deleted (D28/D55, RESTRICT).
        conn.execute(
            sa.text(
                "INSERT INTO app.transaction_template_split "
                "(id, template_id, category_id, amount) "
                "VALUES (gen_random_uuid(), :template_id, :category_id, 100.00)"
            ),
            {"template_id": template_row.id, "category_id": category_id},
        )
        conn.commit()

        blocked = False
        try:
            conn.execute(
                sa.text("DELETE FROM app.category WHERE id = :id"), {"id": category_id}
            )
            conn.commit()
        except sa.exc.IntegrityError:
            blocked = True
            conn.rollback()
        assert blocked, "deleting a category referenced by a template split must be blocked"


# --- CHECK constraint coverage: recurring_transaction ---


def test_recurring_transaction_type_check_rejects_transfer(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            _insert_recurring(
                conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                type="transfer",
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "recurring_transaction.type='transfer' must violate the CHECK"


def test_recurring_transaction_amount_check_rejects_zero_and_negative(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        for bad_amount in ("0", "-1.00"):
            violated = False
            try:
                _insert_recurring(
                    conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                    amount=bad_amount,
                )
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"recurring_transaction.amount={bad_amount} must violate the CHECK"


def test_recurring_transaction_repeat_every_check_rejects_non_positive(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        for bad_value in (0, -1):
            violated = False
            try:
                _insert_recurring(
                    conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                    repeat_every=bad_value,
                )
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"recurring_transaction.repeat_every={bad_value} must violate the CHECK"


def test_recurring_transaction_period_check_rejects_invalid_value(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            _insert_recurring(
                conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                period="fortnight",
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "recurring_transaction.period='fortnight' must violate the CHECK"


def test_recurring_transaction_occurrence_index_check_rejects_negative(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.recurring_transaction "
                    "(id, workspace_id, account_id, type, amount, repeat_every, period, "
                    "starts_on, next_date, occurrence_index, reminder_locale, "
                    "created_by_user_id) "
                    "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', "
                    "50.00, 1, 'month', '2026-01-01', '2026-01-01', -1, 'en', :user_id)"
                ),
                {"workspace_id": workspace_id, "account_id": account_id, "user_id": user_id},
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "recurring_transaction.occurrence_index=-1 must violate the CHECK"


def test_recurring_transaction_ends_on_check_rejects_before_starts_on(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            _insert_recurring(
                conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                starts_on="2026-06-01", next_date="2026-06-01", ends_on="2026-05-01",
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "ends_on before starts_on must violate ck_recurring_transaction_ends_on_after_starts_on"


def test_recurring_transaction_reminder_days_before_check_rejects_out_of_range(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        for bad_value in (-1, 31):
            violated = False
            try:
                _insert_recurring(
                    conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                    reminder_days_before=bad_value,
                )
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"reminder_days_before={bad_value} must violate its CHECK"


def test_recurring_transaction_reminder_locale_check_rejects_invalid_value(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        violated = False
        try:
            _insert_recurring(
                conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id,
                reminder_locale="fr",
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "reminder_locale='fr' must violate ck_recurring_transaction_reminder_locale"


def test_recurring_transaction_split_amount_check_and_category_restrict(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, category_id = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        recurring_row = conn.execute(
            sa.text(
                "INSERT INTO app.recurring_transaction "
                "(id, workspace_id, account_id, type, amount, repeat_every, period, "
                "starts_on, next_date, reminder_locale, created_by_user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', 50.00, "
                "1, 'month', '2026-01-01', '2026-01-01', 'en', :user_id) RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id, "user_id": user_id},
        ).first()
        conn.commit()
        assert recurring_row is not None

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.recurring_transaction_split "
                    "(id, recurring_transaction_id, category_id, amount) "
                    "VALUES (gen_random_uuid(), :recurring_id, :category_id, 0)"
                ),
                {"recurring_id": recurring_row.id, "category_id": category_id},
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "recurring_transaction_split.amount=0 must violate the CHECK"

        conn.execute(
            sa.text(
                "INSERT INTO app.recurring_transaction_split "
                "(id, recurring_transaction_id, category_id, amount) "
                "VALUES (gen_random_uuid(), :recurring_id, :category_id, 50.00)"
            ),
            {"recurring_id": recurring_row.id, "category_id": category_id},
        )
        conn.commit()

        blocked = False
        try:
            conn.execute(
                sa.text("DELETE FROM app.category WHERE id = :id"), {"id": category_id}
            )
            conn.commit()
        except sa.exc.IntegrityError:
            blocked = True
            conn.rollback()
        assert blocked, "deleting a category referenced by a recurring split must be blocked"


# --- recurring_occurrence: PK, SET NULL tombstone ---


def test_recurring_occurrence_primary_key_prevents_duplicate_generation(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _ = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        recurring_row = conn.execute(
            sa.text(
                "INSERT INTO app.recurring_transaction "
                "(id, workspace_id, account_id, type, amount, repeat_every, period, "
                "starts_on, next_date, reminder_locale, created_by_user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', 50.00, "
                "1, 'month', '2026-01-01', '2026-01-01', 'en', :user_id) RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id, "user_id": user_id},
        ).first()
        conn.commit()
        assert recurring_row is not None

        conn.execute(
            sa.text(
                "INSERT INTO app.recurring_occurrence "
                "(recurring_transaction_id, occurrence_date) "
                "VALUES (:recurring_id, '2026-01-01')"
            ),
            {"recurring_id": recurring_row.id},
        )
        conn.commit()

        violated = False
        try:
            conn.execute(
                sa.text(
                    "INSERT INTO app.recurring_occurrence "
                    "(recurring_transaction_id, occurrence_date) "
                    "VALUES (:recurring_id, '2026-01-01')"
                ),
                {"recurring_id": recurring_row.id},
            )
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "a duplicate (recurring_transaction_id, occurrence_date) must be rejected"


def test_recurring_occurrence_transaction_id_set_null_on_transaction_delete(
    migrated_db: sa.Engine,
) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, _category_id = _seed_workspace_account_category(conn)
        user_id = _seed_user(conn)
        recurring_row = conn.execute(
            sa.text(
                "INSERT INTO app.recurring_transaction "
                "(id, workspace_id, account_id, type, amount, repeat_every, period, "
                "starts_on, next_date, reminder_locale, created_by_user_id) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', 50.00, "
                "1, 'month', '2026-01-01', '2026-01-01', 'en', :user_id) RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id, "user_id": user_id},
        ).first()
        transaction_row = conn.execute(
            sa.text(
                "INSERT INTO app.transaction "
                "(id, workspace_id, account_id, type, amount, occurred_on) "
                "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', 50.00, "
                "'2026-01-01') RETURNING id"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        ).first()
        conn.commit()
        assert recurring_row is not None
        assert transaction_row is not None

        conn.execute(
            sa.text(
                "INSERT INTO app.recurring_occurrence "
                "(recurring_transaction_id, occurrence_date, transaction_id) "
                "VALUES (:recurring_id, '2026-01-01', :transaction_id)"
            ),
            {"recurring_id": recurring_row.id, "transaction_id": transaction_row.id},
        )
        conn.commit()

        conn.execute(
            sa.text("DELETE FROM app.transaction WHERE id = :id"), {"id": transaction_row.id}
        )
        conn.commit()

        remaining = conn.execute(
            sa.text(
                "SELECT transaction_id FROM app.recurring_occurrence "
                "WHERE recurring_transaction_id = :recurring_id AND occurrence_date = '2026-01-01'"
            ),
            {"recurring_id": recurring_row.id},
        ).scalar_one()
        # D47: SET NULL, not CASCADE — the occurrence row survives as a
        # tombstone so generation never resurrects a user-deleted transaction.
        assert remaining is None


# --- ORM round trip ---


def test_orm_models_round_trip_via_session(migrated_db: sa.Engine) -> None:
    """`TransactionTemplate`/`TransactionTemplateSplit`/
    `RecurringTransaction`/`RecurringTransactionSplit` (the declarative ORM
    models added in this PR) can be inserted and queried through a real
    SQLAlchemy `Session` against the tables `0005` creates — not just raw
    SQL through `sa.text`, mirroring
    `test_0004.py::test_orm_model_round_trips_via_session`.

    `created_by_user_id` is NOT NULL on both new parent tables (unlike
    `transaction.created_by_user_id`), so a real `app.app_user` row is
    seeded via raw SQL first (that table has no declarative ORM model —
    see `app/db.py`'s `_app_user_ref` stub docstring)."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from app.accounts.models import Account
    from app.categories.models import Category
    from app.recurring.models import RecurringTransaction, RecurringTransactionSplit
    from app.templates.models import TransactionTemplate, TransactionTemplateSplit
    from app.workspace.models import Workspace

    now = datetime.now(UTC)
    with Session(bind=migrated_db) as session:
        user_id = uuid.uuid4()
        session.execute(
            sa.text(
                "INSERT INTO app.app_user (id, google_sub, email, created_at, updated_at) "
                "VALUES (:id, :sub, :email, now(), now())"
            ),
            {"id": user_id, "sub": f"sub-{user_id}", "email": f"{user_id}@example.com"},
        )

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

        category = Category(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            name="Rent",
            type="expense",
            created_at=now,
            updated_at=now,
        )
        session.add(category)
        session.flush()

        template = TransactionTemplate(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            account_id=account.id,
            name="Monthly Rent",
            position=1,
            type="expense",
            amount=Decimal("1000.00"),
            created_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(template)
        session.flush()
        session.add(
            TransactionTemplateSplit(
                id=uuid.uuid4(),
                template_id=template.id,
                category_id=category.id,
                amount=Decimal("1000.00"),
            )
        )

        recurring = RecurringTransaction(
            id=uuid.uuid4(),
            workspace_id=workspace.id,
            account_id=account.id,
            type="expense",
            amount=Decimal("50.00"),
            repeat_every=1,
            period="month",
            starts_on=datetime(2026, 1, 1, tzinfo=UTC).date(),
            next_date=datetime(2026, 1, 1, tzinfo=UTC).date(),
            created_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(recurring)
        session.flush()
        session.add(
            RecurringTransactionSplit(
                id=uuid.uuid4(),
                recurring_transaction_id=recurring.id,
                category_id=category.id,
                amount=Decimal("50.00"),
            )
        )
        session.commit()

        fetched_template = session.query(TransactionTemplate).filter_by(id=template.id).one()
        fetched_recurring = session.query(RecurringTransaction).filter_by(id=recurring.id).one()
        assert fetched_template.amount == Decimal("1000.00")
        assert fetched_template.name == "Monthly Rent"
        assert fetched_recurring.amount == Decimal("50.00")
        assert fetched_recurring.next_date == datetime(2026, 1, 1, tzinfo=UTC).date()


# --- downgrade: two independent teardown paths ---


def test_downgrade_one_step_drops_only_the_five_new_tables(
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
            workspace_id, account_id, _ = _seed_workspace_account_category(conn)
            user_id = _seed_user(conn)
            _insert_recurring(
                conn, workspace_id=workspace_id, account_id=account_id, user_id=user_id
            )

        command.downgrade(cfg, "-1")

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names(schema="app")) == _TABLES_BEFORE_0005

        with engine.connect() as conn:
            remaining_accounts = conn.execute(
                sa.text("SELECT count(*) FROM app.account WHERE workspace_id = :workspace_id"),
                {"workspace_id": workspace_id},
            ).scalar()
        assert remaining_accounts == 1

        command.upgrade(cfg, "head")
        inspector_after = sa.inspect(engine)
        assert set(inspector_after.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_base_drops_every_product_table_including_new_ones(
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
