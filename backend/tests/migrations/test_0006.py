"""RED -> GREEN, design D66-D69, spec `budget-management`: `0006_budgets`
creates exactly the Phase 5 `app.budget` table, enforces its CHECK
constraints and FKs, and cleanly tears down leaving every prior table
(through `0005_templates_and_recurring`) and its rows completely
untouched.

Runs `alembic upgrade`/`downgrade` against a REAL, ephemeral PostgreSQL
server (not a mock, not SQLite) — matching the exact harness
`backend/tests/migrations/test_0002.py`/`test_0003.py`/`test_0005.py`
established.
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
        self.data_dir = tempfile.mkdtemp(prefix="walleza-pg-budgets-migration-test-")
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
    "transaction_template",
    "transaction_template_split",
    "recurring_transaction",
    "recurring_transaction_split",
    "recurring_occurrence",
    "budget",
    "platform_admin",
    "audit_log",
    "alembic_version",
}


def test_head_includes_the_budget_table(migrated_db: sa.Engine) -> None:
    inspector = sa.inspect(migrated_db)
    assert set(inspector.get_table_names(schema="app")) == _ALL_TABLES_AT_HEAD


def _seed_workspace_account_and_category(
    conn: sa.Connection, *, currency: str = "USD"
) -> tuple[str, str, str]:
    workspace_row = conn.execute(
        sa.text("INSERT INTO app.workspace (id, name) VALUES (gen_random_uuid(), 'W') RETURNING id")
    ).first()
    assert workspace_row is not None
    account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Checking', :currency) RETURNING id"
        ),
        {"workspace_id": workspace_row.id, "currency": currency},
    ).first()
    category_row = conn.execute(
        sa.text(
            "INSERT INTO app.category (id, workspace_id, name, type) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Food', 'expense') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    conn.commit()
    assert account_row is not None
    assert category_row is not None
    return str(workspace_row.id), str(account_row.id), str(category_row.id)


def test_budget_amount_positive_check(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, category_id = _seed_workspace_account_and_category(conn)

        for bad_amount in ("0", "-5.00"):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.budget (id, workspace_id, category_id, amount, currency) "
                        "VALUES (gen_random_uuid(), :workspace_id, :category_id, :amount, 'USD')"
                    ),
                    {"workspace_id": workspace_id, "category_id": category_id, "amount": bad_amount},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"budget.amount={bad_amount!r} must violate the CHECK"


def test_budget_currency_iso4217_check(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, category_id = _seed_workspace_account_and_category(conn)

        for bad_currency in ("usd", "US", "USDD", ""):
            violated = False
            try:
                conn.execute(
                    sa.text(
                        "INSERT INTO app.budget (id, workspace_id, category_id, amount, currency) "
                        "VALUES (gen_random_uuid(), :workspace_id, :category_id, 100, :currency)"
                    ),
                    {"workspace_id": workspace_id, "category_id": category_id, "currency": bad_currency},
                )
                conn.commit()
            except sa.exc.IntegrityError:
                violated = True
                conn.rollback()
            assert violated, f"budget.currency={bad_currency!r} must violate the CHECK"


def test_budget_category_restrict_blocks_category_deletion(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, _account_id, category_id = _seed_workspace_account_and_category(conn)
        conn.execute(
            sa.text(
                "INSERT INTO app.budget (id, workspace_id, category_id, amount, currency) "
                "VALUES (gen_random_uuid(), :workspace_id, :category_id, 100, 'USD')"
            ),
            {"workspace_id": workspace_id, "category_id": category_id},
        )
        conn.commit()

        violated = False
        try:
            conn.execute(
                sa.text("DELETE FROM app.category WHERE id = :id"), {"id": category_id}
            )
            conn.commit()
        except sa.exc.IntegrityError:
            violated = True
            conn.rollback()
        assert violated, "deleting a category referenced by a budget must be RESTRICTed (D67)"


def test_budget_account_cascade_deletes_budget(migrated_db: sa.Engine) -> None:
    with migrated_db.connect() as conn:
        workspace_id, account_id, category_id = _seed_workspace_account_and_category(conn)
        budget_row = conn.execute(
            sa.text(
                "INSERT INTO app.budget (id, workspace_id, category_id, account_id, amount, currency) "
                "VALUES (gen_random_uuid(), :workspace_id, :category_id, :account_id, 100, 'USD') "
                "RETURNING id"
            ),
            {"workspace_id": workspace_id, "category_id": category_id, "account_id": account_id},
        ).first()
        conn.commit()
        assert budget_row is not None

        conn.execute(sa.text("DELETE FROM app.account WHERE id = :id"), {"id": account_id})
        conn.commit()

        remaining = conn.execute(
            sa.text("SELECT id FROM app.budget WHERE id = :id"), {"id": budget_row.id}
        ).first()
        assert remaining is None, "deleting the watched account must cascade-delete the budget (D68)"
