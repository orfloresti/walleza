"""RED -> GREEN, design D125-D130, tasks.md Unit 5 (tasks 5.3-5.7):

Exercises `app.ocr.extraction.process` directly against a real ephemeral
Postgres session (no `WorkspaceScope`, no HTTP — mirroring how the real
`app.ocr_worker.handler` calls it), with `app.ocr.textract`'s module-scope
boto3 Textract client mocked (`monkeypatch`) — no real AWS, matching
`tests/transactions/test_attachments.py`'s established S3-mocking
precedent.

Covers design D128's three-way failure taxonomy (one case per table row),
D129's retry/backoff, D130's not-found-retry-once race handler, and the
`SELECT FOR UPDATE` idempotency guard against a duplicate/replayed S3
event on an already-processed draft.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import sqlalchemy as sa
from botocore.exceptions import ClientError
from httpx import ASGITransport, AsyncClient

from app import storage
from app.ocr import extraction, textract
from app.security import issue_access_token


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


def _seed_pending_draft(
    db_session, *, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> uuid.UUID:
    transaction_id = uuid.uuid4()
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction "
            "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
            " is_refund, checked, created_at, updated_at, ocr_status) "
            "VALUES (:id, :ws, :acc, 'expense', 0.01, current_date, NULL, "
            " false, false, now(), now(), 'pending_ocr')"
        ),
        {"id": transaction_id, "ws": workspace_id, "acc": account_id},
    )
    db_session.commit()
    return transaction_id


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": code}},
        operation_name="AnalyzeExpense",
    )


def _good_response(*, total_confidence: float = 98.5) -> dict[str, object]:
    return {
        "ExpenseDocuments": [
            {
                "SummaryFields": [
                    {
                        "Type": {"Text": "TOTAL"},
                        "ValueDetection": {
                            "Text": "45.67",
                            "Confidence": total_confidence,
                        },
                    },
                    {
                        "Type": {"Text": "VENDOR_NAME"},
                        "ValueDetection": {"Text": "Acme Store", "Confidence": 91.0},
                    },
                    {
                        "Type": {"Text": "INVOICE_RECEIPT_DATE"},
                        "ValueDetection": {"Text": "2026-01-15", "Confidence": 87.0},
                    },
                ]
            }
        ]
    }


async def test_transient_error_then_succeeds_on_retry(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-transient-retry@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.side_effect = [
        _client_error("ThrottlingException"),
        _client_error("ThrottlingException"),
        _good_response(),
    ]
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(textract.time, "sleep", MagicMock())
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: "image/jpeg")

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is True
    assert fake_client.analyze_expense.call_count == 3
    row = db_session.execute(
        sa.text(
            "SELECT status, extracted_amount, extracted_vendor_name, attempt_count "
            "FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).one()
    assert row.status == "succeeded"
    assert row.extracted_amount == Decimal("45.67")
    assert row.extracted_vendor_name == "Acme Store"
    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "extracted"


async def test_transient_error_exhausts_all_retries(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-transient-exhausted@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.side_effect = _client_error("ThrottlingException")
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(textract.time, "sleep", MagicMock())
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: None)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is True
    assert fake_client.analyze_expense.call_count == 3
    row = db_session.execute(
        sa.text(
            "SELECT status, failure_reason, attempt_count "
            "FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).one()
    assert row.status == "failed"
    assert row.failure_reason == "provider_unavailable"
    assert row.attempt_count == 3
    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "extraction_failed"


async def test_non_retryable_document_error_fails_immediately(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-non-retryable@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.side_effect = _client_error(
        "UnsupportedDocumentException"
    )
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(textract.time, "sleep", MagicMock())
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: None)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is True
    assert fake_client.analyze_expense.call_count == 1
    row = db_session.execute(
        sa.text(
            "SELECT status, failure_reason, attempt_count "
            "FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).one()
    assert row.status == "failed"
    assert row.failure_reason == "unreadable_document"
    assert row.attempt_count == 1


async def test_low_confidence_success_is_not_a_failure(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-low-confidence@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.return_value = _good_response(total_confidence=58.0)
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: None)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is True
    row = db_session.execute(
        sa.text(
            "SELECT status, field_confidence FROM app.transaction_ocr_extraction "
            "WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).one()
    assert row.status == "succeeded"
    assert row.field_confidence["amount"] == 58.0
    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "extracted"


async def test_genuinely_empty_response_is_no_receipt_detected(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    owner = seed_user(email="ocr-empty-response@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.return_value = {
        "ExpenseDocuments": [{"SummaryFields": []}]
    }
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: None)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is True
    row = db_session.execute(
        sa.text(
            "SELECT status, failure_reason FROM app.transaction_ocr_extraction "
            "WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).one()
    assert row.status == "failed"
    assert row.failure_reason == "no_receipt_detected"
    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "extraction_failed"


async def test_duplicate_invocation_on_already_extracted_is_a_no_op(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    """The `SELECT FOR UPDATE ... WHERE ocr_status = 'pending_ocr'`
    idempotency guard (design D116/D127): a second, replayed invocation
    against a transaction that a previous run already moved to
    `extracted` must not call Textract again and must not touch the
    existing extraction row."""
    owner = seed_user(email="ocr-duplicate-event@example.com")
    cookie = _cookie_for(owner)
    workspace_id, account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    fake_client.analyze_expense.return_value = _good_response()
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(storage, "object_content_type", lambda *, key: None)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    first = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )
    assert first is True
    assert fake_client.analyze_expense.call_count == 1

    second = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert second is False
    assert fake_client.analyze_expense.call_count == 1  # not called again
    count = db_session.execute(
        sa.text(
            "SELECT count(*) FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).scalar_one()
    assert count == 1


async def test_not_found_retries_once_after_delay_then_gives_up(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    """Design D130: a first-attempt miss (the commit-visibility race)
    sleeps once and re-reads before giving up. No transaction row is
    seeded at all here, so both lookups genuinely miss — proving the
    bounded retry, not an infinite loop."""
    owner = seed_user(email="ocr-not-found-race@example.com")
    cookie = _cookie_for(owner)
    workspace_id, _account_id = await _seed_workspace_and_account(app_factory, cookie)
    transaction_id = uuid.uuid4()  # never inserted

    fake_client = MagicMock()
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    sleep_mock = MagicMock()
    monkeypatch.setattr(extraction.time, "sleep", sleep_mock)

    key = storage.receipt_object_key(workspace_id, transaction_id)
    result = extraction.process(
        db_session, workspace_id=workspace_id, transaction_id=transaction_id, key=key
    )

    assert result is False
    sleep_mock.assert_called_once_with(extraction._NOT_FOUND_RETRY_DELAY_SECONDS)
    fake_client.analyze_expense.assert_not_called()


async def test_forged_workspace_transaction_pair_writes_zero_rows(
    seed_user, app_factory, db_session, monkeypatch
) -> None:
    """Threat matrix: cross-tenant write via a forged workspace/transaction
    id pair in a key. A real `pending_ocr` draft exists, but under a
    DIFFERENT workspace than the one the (attacker-controlled) key claims
    — the scoped `SELECT FOR UPDATE` must not find it."""
    owner = seed_user(email="ocr-forged-pair-owner@example.com")
    other = seed_user(email="ocr-forged-pair-other@example.com")
    owner_cookie = _cookie_for(owner)
    other_cookie = _cookie_for(other)
    real_workspace_id, account_id = await _seed_workspace_and_account(
        app_factory, owner_cookie
    )
    _other_workspace_id, _ = await _seed_workspace_and_account(
        app_factory, other_cookie
    )
    transaction_id = _seed_pending_draft(
        db_session, workspace_id=real_workspace_id, account_id=account_id
    )

    fake_client = MagicMock()
    monkeypatch.setattr(textract, "_textract_client", fake_client)
    monkeypatch.setattr(extraction.time, "sleep", MagicMock())

    forged_workspace_id = uuid.uuid4()  # not the real owner
    key = storage.receipt_object_key(forged_workspace_id, transaction_id)
    result = extraction.process(
        db_session,
        workspace_id=forged_workspace_id,
        transaction_id=transaction_id,
        key=key,
    )

    assert result is False
    fake_client.analyze_expense.assert_not_called()
    count = db_session.execute(
        sa.text(
            "SELECT count(*) FROM app.transaction_ocr_extraction WHERE transaction_id = :id"
        ),
        {"id": transaction_id},
    ).scalar_one()
    assert count == 0
    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "pending_ocr"
