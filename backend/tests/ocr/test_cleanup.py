"""Design D124, tasks.md Unit 6 (task 6.3): abandoned-draft TTL sweep.

Exercises `app.ocr.cleanup.sweep_abandoned_drafts` directly against a real
ephemeral Postgres session — mirroring `test_worker.py`'s established
seeding pattern (a real workspace/account via the HTTP app, then a
hand-inserted `app.transaction` row) — with `app.storage.delete_object`
mocked so no real AWS call is made.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app import storage
from app.ocr import cleanup
from app.security import issue_access_token
from app.transactions.models import Transaction


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _seed_workspace_and_account(
    app_factory, cookie: str
) -> tuple[uuid.UUID, uuid.UUID]:
    app = app_factory()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = uuid.UUID(ws.json()["id"])
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": True},
            cookies={"walleza_access": cookie},
        )
        account_id = uuid.UUID(account.json()["id"])
    return workspace_id, account_id


def _seed_transaction(
    db_session,
    *,
    workspace_id: uuid.UUID,
    account_id: uuid.UUID,
    ocr_status: str | None,
    created_at: datetime,
) -> uuid.UUID:
    transaction_id = uuid.uuid4()
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction "
            "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
            " is_refund, checked, created_at, updated_at, ocr_status) "
            "VALUES (:id, :ws, :acc, 'expense', :amount, current_date, NULL, "
            " false, false, :created_at, :created_at, :ocr_status)"
        ),
        {
            "id": transaction_id,
            "ws": workspace_id,
            "acc": account_id,
            "amount": "0.01" if ocr_status is not None else "12.34",
            "created_at": created_at,
            "ocr_status": ocr_status,
        },
    )
    db_session.commit()
    return transaction_id


def _exists(db_session, transaction_id: uuid.UUID) -> bool:
    return (
        db_session.execute(
            sa.select(Transaction.id).where(Transaction.id == transaction_id)
        ).first()
        is not None
    )


async def test_stale_draft_is_swept(seed_user, app_factory, db_session, monkeypatch) -> None:
    owner = seed_user(email="ocr-cleanup-stale@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)

    now = datetime.now(UTC)
    stale_id = _seed_transaction(
        db_session,
        workspace_id=workspace_id,
        account_id=account_id,
        ocr_status="pending_ocr",
        created_at=now - timedelta(days=8),
    )

    delete_mock = MagicMock()
    monkeypatch.setattr(storage, "delete_object", delete_mock)

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 1}
    assert not _exists(db_session, stale_id)
    delete_mock.assert_called_once_with(
        key=storage.receipt_object_key(workspace_id, stale_id)
    )


async def test_young_draft_is_not_swept(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-cleanup-young@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)

    now = datetime.now(UTC)
    young_id = _seed_transaction(
        db_session,
        workspace_id=workspace_id,
        account_id=account_id,
        ocr_status="extracted",
        created_at=now - timedelta(days=6),
    )

    delete_mock = MagicMock()
    monkeypatch.setattr(storage, "delete_object", delete_mock)

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 0}
    assert _exists(db_session, young_id)
    delete_mock.assert_not_called()


async def test_confirmed_transaction_never_swept_regardless_of_age(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-cleanup-confirmed@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)

    now = datetime.now(UTC)
    confirmed_id = _seed_transaction(
        db_session,
        workspace_id=workspace_id,
        account_id=account_id,
        ocr_status="confirmed",
        created_at=now - timedelta(days=365),
    )

    delete_mock = MagicMock()
    monkeypatch.setattr(storage, "delete_object", delete_mock)

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 0}
    assert _exists(db_session, confirmed_id)
    delete_mock.assert_not_called()


async def test_sweep_is_cross_workspace(seed_user, app_factory, db_session, monkeypatch) -> None:
    """Mirrors `generation.run`'s own cross-workspace, scopeless scan
    discipline (design's Data Flow) — one sweep call must reach stale
    drafts in every workspace, not just one."""
    owner_a = seed_user(email="ocr-cleanup-ws-a@example.com")
    owner_b = seed_user(email="ocr-cleanup-ws-b@example.com")
    workspace_a, account_a = await _seed_workspace_and_account(app_factory, _cookie_for(owner_a))
    workspace_b, account_b = await _seed_workspace_and_account(app_factory, _cookie_for(owner_b))

    now = datetime.now(UTC)
    stale_a = _seed_transaction(
        db_session,
        workspace_id=workspace_a,
        account_id=account_a,
        ocr_status="extraction_failed",
        created_at=now - timedelta(days=10),
    )
    stale_b = _seed_transaction(
        db_session,
        workspace_id=workspace_b,
        account_id=account_b,
        ocr_status="pending_ocr",
        created_at=now - timedelta(days=9),
    )

    delete_mock = MagicMock()
    monkeypatch.setattr(storage, "delete_object", delete_mock)

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 2}
    assert not _exists(db_session, stale_a)
    assert not _exists(db_session, stale_b)
    assert delete_mock.call_count == 2


async def test_extraction_row_cascade_deletes_with_draft(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    """FK `transaction_ocr_extraction.transaction_id ON DELETE CASCADE`
    (design D117, migration 0012) means the sweep's plain `DELETE FROM
    app.transaction` needs no explicit companion delete."""
    owner = seed_user(email="ocr-cleanup-cascade@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)

    now = datetime.now(UTC)
    stale_id = _seed_transaction(
        db_session,
        workspace_id=workspace_id,
        account_id=account_id,
        ocr_status="extracted",
        created_at=now - timedelta(days=8),
    )
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction_ocr_extraction "
            "(transaction_id, status, field_confidence, created_at) "
            "VALUES (:id, 'succeeded', '{}'::jsonb, now())"
        ),
        {"id": stale_id},
    )
    db_session.commit()

    monkeypatch.setattr(storage, "delete_object", MagicMock())

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 1}
    remaining = db_session.execute(
        sa.text(
            "SELECT 1 FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": stale_id},
    ).first()
    assert remaining is None


async def test_s3_delete_failure_does_not_undo_db_delete(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    """Best-effort S3 cleanup (module docstring's D27-mirrored ordering):
    an S3-side error must never roll back the already-committed DB
    delete."""
    owner = seed_user(email="ocr-cleanup-s3-fails@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)

    now = datetime.now(UTC)
    stale_id = _seed_transaction(
        db_session,
        workspace_id=workspace_id,
        account_id=account_id,
        ocr_status="pending_ocr",
        created_at=now - timedelta(days=30),
    )

    monkeypatch.setattr(
        storage, "delete_object", MagicMock(side_effect=RuntimeError("s3 boom"))
    )

    counts = cleanup.sweep_abandoned_drafts(db_session, now=now)

    assert counts == {"deleted": 1}
    assert not _exists(db_session, stale_id)
