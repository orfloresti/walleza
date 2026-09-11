"""RED -> GREEN, spec "Templates Carry No Reconciliation or Refund State"
(R7, tasks.md 1.8): neither `checked` nor `is_refund` is settable on a
template create/update request, and a client-sent value for either is
silently ignored by Pydantic's default "ignore unknown fields" behavior
(mirrors `tests/transfers/test_transfer_crud.py`'s `to_amount`-ignored
precedent)."""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token
from app.templates import schemas


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def test_template_create_and_update_schemas_have_no_checked_or_is_refund_field() -> None:
    create_fields = set(schemas.TemplateCreateIn.model_fields)
    update_fields = set(schemas.TemplateUpdateIn.model_fields)
    assert "checked" not in create_fields
    assert "is_refund" not in create_fields
    assert "checked" not in update_fields
    assert "is_refund" not in update_fields
    # R2-style guard, mirrored from templates having no transfer shape either.
    assert "to_account_id" not in create_fields


async def test_client_supplied_checked_and_is_refund_are_silently_ignored(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="tpl-schema@example.com")
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
            "/api/templates",
            json={
                "name": "Rent",
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "checked": True,
                "is_refund": True,
            },
            cookies={"walleza_access": cookie},
        )

    assert created.status_code == 201
    assert "checked" not in created.json()
    assert "is_refund" not in created.json()
