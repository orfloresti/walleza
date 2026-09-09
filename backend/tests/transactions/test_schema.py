"""RED -> GREEN, spec "Type Enum Excludes Transfer" (tasks.md 3.3):
`type` MUST accept only `income`/`expense`, never `transfer` — enforced at
TWO independent layers per design RED #5:

1. The Pydantic schema (`TransactionCreateIn.type: TransactionType =
   Literal["income", "expense"]`) rejects it at the API boundary — tested
   here, end-to-end through the real HTTP surface.
2. The database's own CHECK constraint (`ck_transaction_type`, from PR1's
   `0003_categories_transactions` migration) rejects it independently even
   if a caller somehow bypassed the Pydantic layer — already proven by
   `backend/tests/migrations/test_0003.py
   ::test_transaction_type_check_rejects_transfer` (PR1). Not duplicated
   here; this file owns only the API/schema half of RED #5.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_creating_a_transaction_with_type_transfer_is_rejected_by_the_schema(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="schema-transfer@example.com")
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


async def test_updating_a_transaction_to_type_transfer_is_rejected_by_the_schema(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="schema-transfer-update@example.com")
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

        created = await client.post(
            "/api/transactions",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "occurred_on": "2026-01-15",
            },
            cookies={"walleza_access": cookie},
        )
        transaction_id = created.json()["id"]

        response = await client.patch(
            f"/api/transactions/{transaction_id}",
            json={"type": "transfer"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422
