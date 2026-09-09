"""RED -> GREEN, design D24-D27/D32, spec `transaction-attachments`
(tasks.md 6.1-6.6):

- Authorization strictly precedes issuance: a presigned upload OR
  download URL for a transaction the caller cannot see 404s with
  `app.storage` never invoked at all — not just an HTTP 404, the actual
  storage call is asserted never to have happened (RED #6, and the
  symmetric download-side case, spec's "Another member cannot obtain a
  download URL for the photo" scenario).
- File type/size constraints are enforced BEFORE a URL is issued: an
  out-of-allowlist `Content-Type` is rejected by Pydantic's own 422
  before any presigned URL is generated; the generated presigned POST's
  OWN `Conditions` carry `content-length-range` and an exact
  `Content-Type` — asserted directly, since a unit test cannot literally
  exceed S3's real enforcement without a real upload (design's own
  guidance: presigning is offline, testable with no AWS/moto) (RED #7).
- Confirm with no object actually uploaded -> 409, `photo_uploaded_at`
  stays NULL (RED #8).
- A download URL request 404s identically for an invisible transaction
  and for a visible transaction with no photo yet — same status, no
  oracle (RED #9).
- Deleting a transaction commits the row delete FIRST, then calls
  `storage.delete_object` exactly once; a raised S3 error is logged and
  swallowed — it does not roll back the deletion or fail the response,
  which stays 204 (RED #10, design D27).

Every test here mocks `app.storage`'s module-level functions/client
directly (`monkeypatch`) — no real AWS, no `moto`, matching design D32's
own stated testing strategy.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from httpx import ASGITransport, AsyncClient

from app import storage
from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def _join_same_workspace(client, owner_cookie: str, joiner_cookie: str) -> str:
    """Puts `owner` and `joiner` into the SAME workspace via the real
    invite flow (design D12/D20), mirroring
    `test_transaction_visibility.py`'s own helper exactly."""
    owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
    await client.get("/api/workspace", cookies={"walleza_access": joiner_cookie})

    invite = await client.post("/api/workspace/invites", cookies={"walleza_access": owner_cookie})
    assert invite.status_code == 201
    token = _token_from_url(invite.json()["url"])

    accept = await client.post(
        "/api/workspace/invites/accept",
        json={"token": token},
        cookies={"walleza_access": joiner_cookie},
    )
    assert accept.status_code == 204
    return owner_ws.json()["id"]


async def _create_personal_account(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": True},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_transaction(client, cookie: str, *, account_id: str, notes: str) -> str:
    response = await client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "type": "expense",
            "amount": "42.50",
            "occurred_on": "2026-01-15",
            "notes": notes,
        },
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _fake_presigned_post_payload() -> dict[str, object]:
    return {
        "url": "https://walleza-receipts-test.s3.amazonaws.com/",
        "fields": {"key": "workspaces/.../receipt", "Content-Type": "image/jpeg"},
    }


async def test_upload_url_for_another_workspaces_transaction_404s_before_any_storage_call(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #6: a member of workspace W1 requesting an upload URL for a
    transaction belonging to a DIFFERENT workspace entirely gets 404, and
    `app.storage.presigned_upload` is never invoked at all."""
    owner_w1 = seed_user(email="w1-upload-owner@example.com")
    owner_w2 = seed_user(email="w2-upload-owner@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        account_id = await _create_personal_account(client, cookie_w1, name="W1 account")
        transaction_id = await _create_transaction(
            client, cookie_w1, account_id=account_id, notes="W1's expense"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/photo/upload-url",
            json={"content_type": "image/jpeg"},
            cookies={"walleza_access": cookie_w2},
        )

    assert response.status_code == 404
    fake_presigned_upload.assert_not_called()


async def test_upload_url_for_another_members_personal_account_transaction_404s(
    seed_user, app_factory, monkeypatch
) -> None:
    """Same guarantee as above, but the adversary is a member of the SAME
    workspace, on a DIFFERENT member's personal-account transaction —
    proves the check is `visible_transactions`, not merely a workspace-id
    match."""
    owner_a = seed_user(email="a-upload@example.com")
    owner_b = seed_user(email="b-upload@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)
        account_id = await _create_personal_account(client, cookie_a, name="A's stash")
        transaction_id = await _create_transaction(
            client, cookie_a, account_id=account_id, notes="A's secret expense"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/photo/upload-url",
            json={"content_type": "image/jpeg"},
            cookies={"walleza_access": cookie_b},
        )

    assert response.status_code == 404
    fake_presigned_upload.assert_not_called()


async def test_wrong_content_type_rejected_before_any_url_is_issued(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #7 (type half): an out-of-allowlist `Content-Type` (design D25:
    only jpeg/png/webp/heic) is rejected by Pydantic's own 422 before the
    request handler runs at all, so `app.storage.presigned_upload` is
    never invoked."""
    owner = seed_user(email="wrong-content-type@example.com")

    fake_presigned_upload = MagicMock(return_value=_fake_presigned_post_payload())
    monkeypatch.setattr(storage, "presigned_upload", fake_presigned_upload)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="needs a receipt"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/photo/upload-url",
            json={"content_type": "application/pdf"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422
    fake_presigned_upload.assert_not_called()


async def test_presigned_post_policy_carries_content_length_range_and_exact_content_type(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #7 (size half): a unit test cannot literally exceed S3's real
    enforcement without a real upload, so this asserts the GENERATED
    policy's own `Conditions` directly — `content-length-range` bounded
    by `settings.receipt_max_bytes`, and an EXACT `Content-Type`
    condition matching what the caller declared (design D25). Mocks only
    the module-scope boto3 client (`app.storage._s3_client`), never
    `presigned_upload` itself, so the REAL policy-construction code runs
    and is what gets asserted on."""
    owner = seed_user(email="policy-conditions@example.com")

    fake_s3_client = MagicMock()
    fake_s3_client.generate_presigned_post.return_value = _fake_presigned_post_payload()
    monkeypatch.setattr(storage, "_s3_client", fake_s3_client)

    from app.config import get_settings

    settings = get_settings()

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="needs a receipt"
        )

        response = await client.post(
            f"/api/transactions/{transaction_id}/photo/upload-url",
            json={"content_type": "image/png"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["max_bytes"] == settings.receipt_max_bytes
    assert body["content_type"] == "image/png"

    fake_s3_client.generate_presigned_post.assert_called_once()
    call_kwargs = fake_s3_client.generate_presigned_post.call_args.kwargs
    conditions = call_kwargs["Conditions"]
    assert {"Content-Type": "image/png"} in conditions
    assert ["content-length-range", 1, settings.receipt_max_bytes] in conditions
    assert call_kwargs["ExpiresIn"] == settings.presigned_url_ttl_seconds


async def test_confirm_with_no_object_uploaded_returns_409_and_leaves_photo_fields_null(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #8: `app.storage.object_exists` is mocked to report the object
    is NOT there (the caller requested an upload URL but never actually
    completed the upload); confirm rejects with 409 and
    `photo_uploaded_at`/`photo_content_type` stay NULL, so the DB's
    `(photo_content_type IS NULL) = (photo_uploaded_at IS NULL)` CHECK
    still trivially holds."""
    owner = seed_user(email="confirm-no-object@example.com")

    monkeypatch.setattr(storage, "object_exists", MagicMock(return_value=False))

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="needs a receipt"
        )

        confirm_response = await client.put(
            f"/api/transactions/{transaction_id}/photo",
            json={"content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )
        fetched = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert confirm_response.status_code == 409
    body = fetched.json()
    assert body["photo_content_type"] is None
    assert body["photo_uploaded_at"] is None


async def test_confirm_with_object_actually_uploaded_succeeds(
    seed_user, app_factory, monkeypatch
) -> None:
    """The GREEN counterpart of the above: `object_exists` reports the
    object IS there, so confirm sets both photo fields and they round-trip
    on a subsequent fetch."""
    owner = seed_user(email="confirm-object-present@example.com")

    monkeypatch.setattr(storage, "object_exists", MagicMock(return_value=True))

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="needs a receipt"
        )

        confirm_response = await client.put(
            f"/api/transactions/{transaction_id}/photo",
            json={"content_type": "image/jpeg"},
            cookies={"walleza_access": cookie},
        )
        fetched = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["photo_content_type"] == "image/jpeg"
    assert confirm_response.json()["photo_uploaded_at"] is not None

    body = fetched.json()
    assert body["photo_content_type"] == "image/jpeg"
    assert body["photo_uploaded_at"] is not None


async def test_download_url_404s_identically_for_invisible_and_visible_no_photo_transactions(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #9: a caller must not be able to distinguish "transaction I
    cannot see" from "transaction I can see but with no photo" by status
    code alone — both cases are 404, and `app.storage.presigned_download`
    is never invoked in either."""
    owner_a = seed_user(email="a-download-404@example.com")
    owner_b = seed_user(email="b-download-404@example.com")

    fake_presigned_download = MagicMock(return_value="https://signed-get-url")
    monkeypatch.setattr(storage, "presigned_download", fake_presigned_download)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)
        account_id = await _create_personal_account(client, cookie_a, name="A's stash")

        invisible_transaction_id = await _create_transaction(
            client, cookie_a, account_id=account_id, notes="A's hidden expense"
        )
        visible_no_photo_id = await _create_transaction(
            client, cookie_a, account_id=account_id, notes="A's own, no photo"
        )

        invisible_response = await client.get(
            f"/api/transactions/{invisible_transaction_id}/photo",
            cookies={"walleza_access": cookie_b},
        )
        visible_no_photo_response = await client.get(
            f"/api/transactions/{visible_no_photo_id}/photo",
            cookies={"walleza_access": cookie_a},
        )

    assert invisible_response.status_code == 404
    assert visible_no_photo_response.status_code == 404
    fake_presigned_download.assert_not_called()


async def test_another_member_cannot_obtain_download_url_for_a_confirmed_photo(
    seed_user, app_factory, monkeypatch
) -> None:
    """Spec's "Another member cannot obtain a download URL for the photo"
    scenario: member A has a CONFIRMED photo on a personal-account
    transaction; member B (same workspace) requests a download URL for it
    and is rejected 404 before any presigned GET is generated."""
    owner_a = seed_user(email="a-download-confirmed@example.com")
    owner_b = seed_user(email="b-download-confirmed@example.com")

    monkeypatch.setattr(storage, "object_exists", MagicMock(return_value=True))
    fake_presigned_download = MagicMock(return_value="https://signed-get-url")
    monkeypatch.setattr(storage, "presigned_download", fake_presigned_download)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await _join_same_workspace(client, cookie_a, cookie_b)
        account_id = await _create_personal_account(client, cookie_a, name="A's stash")
        transaction_id = await _create_transaction(
            client, cookie_a, account_id=account_id, notes="A's photographed expense"
        )
        confirm = await client.put(
            f"/api/transactions/{transaction_id}/photo",
            json={"content_type": "image/jpeg"},
            cookies={"walleza_access": cookie_a},
        )
        assert confirm.status_code == 200

        b_response = await client.get(
            f"/api/transactions/{transaction_id}/photo",
            cookies={"walleza_access": cookie_b},
        )
        a_response = await client.get(
            f"/api/transactions/{transaction_id}/photo",
            cookies={"walleza_access": cookie_a},
        )

    assert b_response.status_code == 404
    assert a_response.status_code == 200
    assert "url" in a_response.json()
    fake_presigned_download.assert_called_once()


async def test_delete_transaction_commits_db_delete_then_calls_delete_object_once(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #10 (happy path half): deleting a transaction calls
    `app.storage.delete_object` exactly once, with the transaction's own
    derived object key, AFTER the row is already gone (204, then a
    subsequent GET 404s)."""
    owner = seed_user(email="delete-calls-storage@example.com")

    fake_delete_object = MagicMock(return_value=None)
    monkeypatch.setattr(storage, "delete_object", fake_delete_object)

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = workspace.json()["id"]
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="to be deleted"
        )

        delete_response = await client.delete(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )
        fetch_after_delete = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert fetch_after_delete.status_code == 404
    fake_delete_object.assert_called_once_with(
        key=storage.receipt_object_key(uuid.UUID(workspace_id), uuid.UUID(transaction_id))
    )


async def test_delete_transaction_survives_an_s3_delete_object_exception(
    seed_user, app_factory, monkeypatch
) -> None:
    """RED #10 (failure half, design D27's whole point): `delete_object`
    raising does NOT roll back the already-committed DB delete and does
    NOT fail the response — it stays 204, and the row stays deleted on a
    subsequent fetch."""
    owner = seed_user(email="delete-s3-fails@example.com")

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated S3 outage")

    monkeypatch.setattr(storage, "delete_object", MagicMock(side_effect=_raise))

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_personal_account(client, cookie, name="Checking")
        transaction_id = await _create_transaction(
            client, cookie, account_id=account_id, notes="delete despite s3 outage"
        )

        delete_response = await client.delete(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )
        fetch_after_delete = await client.get(
            f"/api/transactions/{transaction_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert fetch_after_delete.status_code == 404
