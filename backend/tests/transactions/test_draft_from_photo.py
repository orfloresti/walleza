"""RED -> GREEN, design D119/D122/D123/D131, tasks.md Unit 3 (task 3.4):

- `POST /api/transactions/draft-from-photo` creates a draft transaction
  (`ocr_status='pending_ocr'`, placeholder `amount=0.01`, no splits) and
  returns a presigned upload URL for that transaction's receipt key,
  mirroring the existing `request_photo_upload_url` presign shape.
- `account_id` must resolve inside the caller's own `visible_accounts`
  (design D119) — a foreign-workspace or another member's personal
  account is rejected with 422, exactly like `POST /api/transactions`.
- Design D122's daily cap: the 20th draft in a UTC calendar day succeeds,
  the 21st is rejected with 429, a `Retry-After` header, and a
  `{limit, used, resets_at}` body — with NO row and NO presigned URL
  produced for the rejected 21st request. The cap resets the next UTC
  day, proven by rewinding already-created drafts' `created_at` into
  yesterday via direct SQL rather than waiting a real day.

Every test mocks `app.storage.presigned_upload` directly (`monkeypatch`),
no real AWS/moto, matching the existing `test_attachments.py` precedent.
"""

from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app import storage
from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _fake_presigned_post_payload() -> dict[str, object]:
    return {
        "url": "https://walleza-receipts-test.s3.amazonaws.com/",
        "fields": {"key": "workspaces/.../receipt", "Content-Type": "image/jpeg"},
    }


async def _create_personal_account(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": True},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_draft_from_photo_creates_pending_draft_and_returns_presigned_url(
    seed_user, app_factory, monkeypatch
) -> None:
    owner = seed_user(email="draft-happy@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")

        response = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["transaction_id"])
    assert body["url"] == "https://walleza-receipts-test.s3.amazonaws.com/"
    assert body["fields"]["Content-Type"] == "image/jpeg"
    assert body["max_bytes"] > 0
    assert body["content_type"] == "image/jpeg"
    fake_presigned_upload.assert_called_once()


async def test_draft_from_photo_rejects_foreign_workspace_account_id(
    seed_user, app_factory, monkeypatch
) -> None:
    owner_w1 = seed_user(email="draft-w1@example.com")
    owner_w2 = seed_user(email="draft-w2@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})
        account_id_w1 = await _create_personal_account(client, cookie_w1, name="W1 account")

        response = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id_w1, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie_w2},
        )

    assert response.status_code == 422
    fake_presigned_upload.assert_not_called()


async def test_draft_from_photo_rejects_another_members_personal_account(
    seed_user, app_factory, monkeypatch
) -> None:
    """Workspace isolation within the SAME workspace: member B cannot
    create a draft against member A's personal account."""
    from tests.transactions.test_attachments import _join_same_workspace

    owner_a = seed_user(email="draft-a@example.com")
    owner_b = seed_user(email="draft-b@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)
        account_id_a = await _create_personal_account(client, cookie_a, name="A's stash")

        response = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id_a, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie_b},
        )

    assert response.status_code == 422
    fake_presigned_upload.assert_not_called()


async def test_daily_limit_20th_succeeds_21st_rejected_with_429(
    seed_user, app_factory, monkeypatch, db_session
) -> None:
    """Design D122/D123: seeds 19 already-created drafts directly via SQL
    (cheaper than round-tripping through the endpoint 19 times), then
    proves the 20th request through the REAL endpoint succeeds and the
    21st is rejected with 429 + `Retry-After` + the documented body, with
    no 21st row created."""
    owner = seed_user(email="draft-limit@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie, name="Checking")

        for i in range(19):
            db_session.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
                    " is_refund, checked, created_at, updated_at, ocr_status) "
                    "VALUES (:id, :ws, :acc, 'expense', 0.01, current_date, NULL, "
                    " false, false, now(), now(), 'pending_ocr')"
                ),
                {"id": uuid.uuid4(), "ws": workspace_id, "acc": account_id},
            )
        db_session.commit()

        before_count = db_session.execute(
            sa.text(
                "SELECT count(*) FROM app.transaction "
                "WHERE workspace_id = :ws AND ocr_status IS NOT NULL"
            ),
            {"ws": workspace_id},
        ).scalar_one()
        assert before_count == 19

        response_20 = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )
        assert response_20.status_code == 201

        response_21 = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )

    assert response_21.status_code == 429
    assert "Retry-After" in response_21.headers
    body = response_21.json()["detail"]
    assert body["limit"] == 20
    assert body["used"] == 20
    assert "resets_at" in body

    after_count = db_session.execute(
        sa.text(
            "SELECT count(*) FROM app.transaction "
            "WHERE workspace_id = :ws AND ocr_status IS NOT NULL"
        ),
        {"ws": workspace_id},
    ).scalar_one()
    assert after_count == 20


async def test_daily_limit_resets_next_utc_day(
    seed_user, app_factory, monkeypatch, db_session
) -> None:
    """Design D122: 20 drafts created "yesterday" (via a rewound
    `created_at`) must not count against today's limit — the 21st
    request of a NEW UTC day succeeds."""
    owner = seed_user(email="draft-reset@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        ws = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = ws.json()["id"]
        account_id = await _create_personal_account(client, cookie, name="Checking")

        yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
        for i in range(20):
            db_session.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on, notes, "
                    " is_refund, checked, created_at, updated_at, ocr_status) "
                    "VALUES (:id, :ws, :acc, 'expense', 0.01, current_date, NULL, "
                    " false, false, :created_at, :created_at, 'pending_ocr')"
                ),
                {
                    "id": uuid.uuid4(),
                    "ws": workspace_id,
                    "acc": account_id,
                    "created_at": yesterday,
                },
            )
        db_session.commit()

        response = await client.post(
            "/api/transactions/draft-from-photo",
            json={"account_id": account_id, "content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
