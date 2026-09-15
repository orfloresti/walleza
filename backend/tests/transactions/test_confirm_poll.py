"""RED -> GREEN, design D131/D116, tasks.md Unit 4 (tasks 4.1-4.3):

- `GET /api/transactions/{id}/ocr` returns the current `ocr_status` plus
  the extraction result once one exists — resolved via the same
  `visible_transactions` / `ocr_draft_transactions` union `delete_transaction`
  already uses, since a draft is invisible through the default path
  (design D120).
- `POST /api/transactions/{id}/confirm-from-photo` reuses `create_transaction`'s
  validators, requires a non-empty `splits` (spec's "Category Always
  Manual"), and transitions `ocr_status` to `confirmed` via design D116's
  conditional UPDATE — valid FROM states are exactly `extracted` and
  `extraction_failed`. `pending_ocr` is NOT a valid source state (no
  "skip OCR" escape hatch — recorded as a judgment call in apply-progress,
  confirmed against design D116's literal WHERE clause).

Unit 5 (the real OCR worker) has not been built yet, so every test here
manually sets `ocr_status`/inserts a `transaction_ocr_extraction` row via
raw SQL to simulate the worker's future output, exactly as
`test_daily_limit_20th_succeeds_21st_rejected_with_429` seeds drafts
out-of-band.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_personal_account(client, cookie: str, *, name: str = "Checking") -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": True},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_category(client, cookie: str, *, name: str, type_: str = "expense") -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": type_},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _seed_draft(
    db_session, *, workspace_id: str, account_id: str, ocr_status: str
) -> uuid.UUID:
    transaction_id = uuid.uuid4()
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction "
            "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
            " is_refund, checked, created_at, updated_at, ocr_status) "
            "VALUES (:id, :ws, :acc, 'expense', 0.01, current_date, NULL, "
            " false, false, now(), now(), :status)"
        ),
        {"id": transaction_id, "ws": workspace_id, "acc": account_id, "status": ocr_status},
    )
    db_session.commit()
    return transaction_id


def _seed_extraction(
    db_session,
    *,
    transaction_id: uuid.UUID,
    status: str,
    failure_reason: str | None = None,
    amount: str | None = None,
    vendor_name: str | None = None,
) -> None:
    db_session.execute(
        sa.text(
            "INSERT INTO app.transaction_ocr_extraction "
            "(transaction_id, status, failure_reason, extracted_amount, "
            " extracted_occurred_on, extracted_vendor_name, extracted_currency, "
            " field_confidence, raw_response, provider, attempt_count, created_at) "
            "VALUES (:tx, :status, :failure_reason, :amount, current_date, :vendor, "
            " 'USD', '{\"amount\": 91.2}'::jsonb, NULL, 'textract', 1, now())"
        ),
        {
            "tx": transaction_id,
            "status": status,
            "failure_reason": failure_reason,
            "amount": amount,
            "vendor": vendor_name,
        },
    )
    db_session.commit()


async def test_poll_pending_ocr_has_no_extraction(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="poll-pending@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="pending_ocr"
        )

        response = await client.get(
            f"/api/transactions/{transaction_id}/ocr",
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ocr_status"] == "pending_ocr"
    assert body["extraction"] is None


async def test_poll_extracted_returns_extraction_fields(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="poll-extracted@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )
        _seed_extraction(
            db_session,
            transaction_id=transaction_id,
            status="succeeded",
            amount="42.50",
            vendor_name="Corner Store",
        )

        response = await client.get(
            f"/api/transactions/{transaction_id}/ocr",
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ocr_status"] == "extracted"
    assert body["extraction"]["status"] == "succeeded"
    assert body["extraction"]["amount"] == "42.50"
    assert body["extraction"]["vendor_name"] == "Corner Store"
    assert body["extraction"]["failure_reason"] is None
    assert body["extraction"]["field_confidence"]["amount"] == 91.2


async def test_poll_extraction_failed_returns_failure_reason(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="poll-failed@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)

        transaction_id = _seed_draft(
            db_session,
            workspace_id=workspace_id,
            account_id=account_id,
            ocr_status="extraction_failed",
        )
        _seed_extraction(
            db_session,
            transaction_id=transaction_id,
            status="failed",
            failure_reason="no_receipt_detected",
        )

        response = await client.get(
            f"/api/transactions/{transaction_id}/ocr",
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ocr_status"] == "extraction_failed"
    assert body["extraction"]["status"] == "failed"
    assert body["extraction"]["failure_reason"] == "no_receipt_detected"
    assert body["extraction"]["amount"] is None


async def test_poll_cross_workspace_draft_is_404(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="poll-owner@example.com")
    stranger = seed_user(email="poll-stranger@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_owner = _cookie_for(owner)
    cookie_stranger = _cookie_for(stranger)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie_owner})
        workspace_id = ws.json()["id"]
        await client.get("/api/workspace", cookies={"walleza_access": cookie_stranger})
        account_id = await _create_personal_account(client, cookie_owner)

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )

        response = await client.get(
            f"/api/transactions/{transaction_id}/ocr",
            cookies={"walleza_access": cookie_stranger},
        )

    assert response.status_code == 404


async def test_confirm_from_extracted_creates_split_and_updates_amount(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="confirm-extracted@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Groceries")

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )
        _seed_extraction(
            db_session, transaction_id=transaction_id, status="succeeded", amount="42.50"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "42.50",
                "occurred_on": "2026-09-15",
                "splits": [{"category_id": category_id, "amount": "42.50"}],
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["amount"]) == Decimal("42.50")
    assert len(body["splits"]) == 1
    assert body["splits"][0]["category_id"] == category_id

    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "confirmed"


async def test_confirm_from_extraction_failed_manual_fallback(
    seed_user, app_factory, db_session
) -> None:
    owner = seed_user(email="confirm-failed@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Transport")

        transaction_id = _seed_draft(
            db_session,
            workspace_id=workspace_id,
            account_id=account_id,
            ocr_status="extraction_failed",
        )
        _seed_extraction(
            db_session,
            transaction_id=transaction_id,
            status="failed",
            failure_reason="unreadable_document",
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "15.00",
                "occurred_on": "2026-09-15",
                "splits": [{"category_id": category_id, "amount": "15.00"}],
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 200
    assert Decimal(response.json()["amount"]) == Decimal("15.00")


async def test_confirm_rejects_pending_ocr_no_escape_hatch(
    seed_user, app_factory, db_session
) -> None:
    """Design D116 lists only `extracted`/`extraction_failed` as valid
    source states for the confirm transition — `pending_ocr` (no
    extraction yet) is NOT confirmable directly."""
    owner = seed_user(email="confirm-pending@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Misc")

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="pending_ocr"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-09-15",
                "splits": [{"category_id": category_id, "amount": "10.00"}],
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 409


async def test_confirm_rejects_double_confirm(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="confirm-double@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Groceries")

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )
        _seed_extraction(
            db_session, transaction_id=transaction_id, status="succeeded", amount="20.00"
        )

        body = {
            "account_id": account_id,
            "type": "expense",
            "amount": "20.00",
            "occurred_on": "2026-09-15",
            "splits": [{"category_id": category_id, "amount": "20.00"}],
        }

        first = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json=body,
            cookies={"walleza_access": cookie},
        )
        assert first.status_code == 200

        second = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json=body,
            cookies={"walleza_access": cookie},
        )

    assert second.status_code == 409


async def test_confirm_without_category_rejected(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="confirm-no-category@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie)

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )
        _seed_extraction(
            db_session, transaction_id=transaction_id, status="succeeded", amount="20.00"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "20.00",
                "occurred_on": "2026-09-15",
                "splits": [],
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422

    ocr_status = db_session.execute(
        sa.text("SELECT ocr_status FROM app.transaction WHERE id = :id"),
        {"id": transaction_id},
    ).scalar_one()
    assert ocr_status == "extracted"


async def test_confirm_cross_workspace_draft_is_404(seed_user, app_factory, db_session) -> None:
    owner = seed_user(email="confirm-owner@example.com")
    stranger = seed_user(email="confirm-stranger@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_owner = _cookie_for(owner)
    cookie_stranger = _cookie_for(stranger)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie_owner})
        workspace_id = ws.json()["id"]
        await client.get("/api/workspace", cookies={"walleza_access": cookie_stranger})
        account_id = await _create_personal_account(client, cookie_owner)
        category_id = await _create_category(client, cookie_stranger, name="Stranger cat")

        transaction_id = _seed_draft(
            db_session, workspace_id=workspace_id, account_id=account_id, ocr_status="extracted"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/confirm-from-photo",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-09-15",
                "splits": [{"category_id": category_id, "amount": "10.00"}],
            },
            cookies={"walleza_access": cookie_stranger},
        )

    assert response.status_code == 404
