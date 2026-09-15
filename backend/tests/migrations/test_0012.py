"""RED -> GREEN: `0012_ocr_drafts` adds `app.transaction.ocr_status` (design
D115) and creates `app.transaction_ocr_extraction` (design D117) with the
exact shape the design requires — a CHECK-constrained value domain on
`ocr_status`, a partial index, a 1:1 PK on `transaction_id`, and the
paired failure-reason CHECK idiom. Also proves the rollback ordering: a
downgrade removes every non-confirmed draft BEFORE dropping the column, so
no `amount=0.01` sentinel row is ever left behind (design "Migration /
Rollout"). Follows the same real-Postgres harness `test_0008.py` through
`test_0011.py` established.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC
from decimal import Decimal
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


def _seed_workspace_and_account(conn: sa.Connection, *, owner_id: str) -> tuple[str, str]:
    workspace_row = conn.execute(
        sa.text(
            "INSERT INTO app.workspace (id, name, created_by_user_id, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'W', :owner, now(), now()) RETURNING id"
        ),
        {"owner": owner_id},
    ).first()
    assert workspace_row is not None
    account_row = conn.execute(
        sa.text(
            "INSERT INTO app.account (id, workspace_id, name, currency) "
            "VALUES (gen_random_uuid(), :workspace_id, 'Checking', 'USD') RETURNING id"
        ),
        {"workspace_id": workspace_row.id},
    ).first()
    assert account_row is not None
    return str(workspace_row.id), str(account_row.id)


def _insert_transaction(
    conn: sa.Connection,
    *,
    workspace_id: str,
    account_id: str,
    ocr_status: str | None,
    amount: str = "10.00",
) -> str:
    row = conn.execute(
        sa.text(
            "INSERT INTO app.transaction "
            "(id, workspace_id, account_id, type, amount, occurred_on, "
            "created_at, updated_at, ocr_status) "
            "VALUES (gen_random_uuid(), :workspace_id, :account_id, 'expense', :amount, "
            "current_date, now(), now(), :ocr_status) RETURNING id"
        ),
        {
            "workspace_id": workspace_id,
            "account_id": account_id,
            "amount": Decimal(amount),
            "ocr_status": ocr_status,
        },
    ).first()
    assert row is not None
    return str(row.id)


def test_ocr_status_check_rejects_invalid_value(
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
            owner_id = _seed_user(conn, email="ocr-owner@example.com")
            workspace_id, account_id = _seed_workspace_and_account(conn, owner_id=owner_id)

        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="not_a_real_status",
            )
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_ocr_status_accepts_null_and_each_valid_value(
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
            owner_id = _seed_user(conn, email="ocr-valid-owner@example.com")
            workspace_id, account_id = _seed_workspace_and_account(conn, owner_id=owner_id)

            for status in (None, "pending_ocr", "extracted", "extraction_failed", "confirmed"):
                _insert_transaction(
                    conn, workspace_id=workspace_id, account_id=account_id, ocr_status=status
                )

        with engine.connect() as conn:
            count = conn.execute(
                sa.text(
                    "SELECT count(*) FROM app.transaction WHERE workspace_id = :ws"
                ),
                {"ws": workspace_id},
            ).scalar()
        assert count == 5
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_extraction_table_fk_and_check_behaviour(
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
            owner_id = _seed_user(conn, email="ocr-fk-owner@example.com")
            workspace_id, account_id = _seed_workspace_and_account(conn, owner_id=owner_id)
            transaction_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="extracted",
            )
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_ocr_extraction "
                    "(transaction_id, status, extracted_amount, extracted_vendor_name, "
                    "field_confidence, created_at) "
                    "VALUES (:tid, 'succeeded', 12.34, 'Corner Store', "
                    "'{\"amount\": 98.5}'::jsonb, now())"
                ),
                {"tid": transaction_id},
            )

        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status, extracted_vendor_name, field_confidence "
                    "FROM app.transaction_ocr_extraction WHERE transaction_id = :tid"
                ),
                {"tid": transaction_id},
            ).first()
        assert row is not None
        assert row.status == "succeeded"
        assert row.extracted_vendor_name == "Corner Store"
        assert row.field_confidence == {"amount": 98.5}

        # 1:1 PK — a second insert for the same transaction_id violates the PK.
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_ocr_extraction "
                    "(transaction_id, status, created_at) "
                    "VALUES (:tid, 'succeeded', now())"
                ),
                {"tid": transaction_id},
            )

        # Paired CHECK: status='failed' requires a failure_reason, and vice versa.
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            other_transaction_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="extraction_failed",
            )
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_ocr_extraction "
                    "(transaction_id, status, created_at) "
                    "VALUES (:tid, 'failed', now())"
                ),
                {"tid": other_transaction_id},
            )

        # Failure reason domain is enforced.
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            other_transaction_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="extraction_failed",
            )
            conn.execute(
                sa.text(
                    "INSERT INTO app.transaction_ocr_extraction "
                    "(transaction_id, status, failure_reason, created_at) "
                    "VALUES (:tid, 'failed', 'not_a_real_reason', now())"
                ),
                {"tid": other_transaction_id},
            )

        # ON DELETE CASCADE: deleting the transaction removes the extraction row.
        with engine.begin() as conn:
            conn.execute(
                sa.text("DELETE FROM app.transaction WHERE id = :tid"),
                {"tid": transaction_id},
            )
        with engine.connect() as conn:
            remaining = conn.execute(
                sa.text(
                    "SELECT count(*) FROM app.transaction_ocr_extraction WHERE transaction_id = :tid"
                ),
                {"tid": transaction_id},
            ).scalar()
        assert remaining == 0
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_downgrade_removes_non_confirmed_drafts_before_dropping_column(
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
            owner_id = _seed_user(conn, email="ocr-downgrade-owner@example.com")
            workspace_id, account_id = _seed_workspace_and_account(conn, owner_id=owner_id)

            draft_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="pending_ocr",
                amount="0.01",
            )
            confirmed_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status="confirmed",
                amount="42.00",
            )
            ordinary_id = _insert_transaction(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                ocr_status=None,
                amount="7.50",
            )

        command.downgrade(cfg, "0011")

        with engine.connect() as conn:
            remaining_ids = {
                str(r.id)
                for r in conn.execute(
                    sa.text("SELECT id FROM app.transaction WHERE workspace_id = :ws"),
                    {"ws": workspace_id},
                )
            }
        assert draft_id not in remaining_ids
        assert confirmed_id in remaining_ids
        assert ordinary_id in remaining_ids

        inspector = sa.inspect(engine)
        transaction_cols = {c["name"] for c in inspector.get_columns("transaction", schema="app")}
        assert "ocr_status" not in transaction_cols
        assert "transaction_ocr_extraction" not in inspector.get_table_names(schema="app")
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()


def test_orm_round_trip(
    real_postgres: _EphemeralPostgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.accounts.models import (
        Account,  # noqa: F401 - registers app.account for the FK
    )
    from app.config import get_settings
    from app.transactions.models import OcrStatus, Transaction
    from app.transactions.ocr_models import TransactionOcrExtraction
    from app.workspace.models import (
        Workspace,  # noqa: F401 - registers app.workspace for the FK
    )

    monkeypatch.setenv("WALLEZA_MIGRATIONS_DATABASE_URL", real_postgres.admin_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = sa.create_engine(real_postgres.admin_url)
    try:
        command.upgrade(cfg, "head")

        with engine.begin() as conn:
            owner_id = _seed_user(conn, email="ocr-orm-owner@example.com")
            workspace_id, account_id = _seed_workspace_and_account(conn, owner_id=owner_id)

        from datetime import datetime

        from sqlalchemy.orm import Session

        with Session(engine) as session:
            txn = Transaction(
                id=uuid.uuid4(),
                workspace_id=uuid.UUID(workspace_id),
                account_id=uuid.UUID(account_id),
                type="expense",
                amount=Decimal("0.01"),
                occurred_on=datetime.now(UTC).date(),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                ocr_status=OcrStatus.PENDING_OCR,
            )
            session.add(txn)
            session.flush()

            extraction = TransactionOcrExtraction(
                transaction_id=txn.id,
                status="succeeded",
                extracted_amount=Decimal("19.99"),
                extracted_vendor_name="Bodega",
                field_confidence={"amount": 96.2},
                created_at=datetime.now(UTC),
            )
            session.add(extraction)
            session.commit()

            fetched = session.get(TransactionOcrExtraction, txn.id)
            assert fetched is not None
            assert fetched.status == "succeeded"
            assert fetched.extracted_vendor_name == "Bodega"
            assert fetched.field_confidence == {"amount": 96.2}
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()
        get_settings.cache_clear()
