"""RED -> GREEN: `transfer-management`'s schema shape (spec "Transfers
Carry No Category Association") and the cross-phase regression guard
that Phase 2's own transaction `type` CHECK still rejects `'transfer'`
completely unmodified by this phase (design RED #15).
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token
from app.transfers.schemas import TransferCreateIn


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def test_transfer_create_schema_has_no_category_or_split_fields() -> None:
    fields = set(TransferCreateIn.model_fields.keys())
    assert "category_id" not in fields
    assert "splits" not in fields
    # And no to_amount input field either — D40/spec: always server-derived.
    assert "to_amount" not in fields


async def test_posting_a_transaction_with_type_transfer_still_fails_schema_and_db_check(
    seed_user, app_factory
) -> None:
    """Phase 2's own RED test #5 (`backend/tests/transactions/test_schema.
    py::test_creating_a_transaction_with_type_transfer_is_rejected_by_the_
    schema` and `backend/tests/migrations/test_0003.py::
    test_transaction_type_check_rejects_transfer_and_invalid`) is NOT
    modified by this phase — this is a FRESH confirmation, exercised
    against the transfers test harness/migration chain (which now
    includes 0004), that both layers still reject it unmodified."""
    owner = seed_user(email="xfer-schema-regression@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account = await client.post(
            "/api/accounts",
            json={"name": "Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie},
        )
        account_id = account.json()["id"]

        response = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "transfer",
                "amount": "10.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422
