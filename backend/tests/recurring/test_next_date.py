"""RED -> GREEN, spec "next_date Is Server-Managed" (tasks.md 1.15):
`next_date` initializes from `starts_on` at creation, and a client update
to any other field MUST NOT reset or otherwise alter it."""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": "Checking", "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_next_date_initializes_from_starts_on(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-next-date-init@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-03-15",
            },
            cookies={"walleza_access": cookie},
        )

    assert created.status_code == 201
    assert created.json()["next_date"] == "2026-03-15"
    assert created.json()["starts_on"] == "2026-03-15"
    assert created.json()["occurrence_index"] == 0


async def test_editing_notes_leaves_next_date_byte_identical(seed_user, app_factory) -> None:
    owner = seed_user(email="rec-next-date-untouched@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-03-15",
            },
            cookies={"walleza_access": cookie},
        )
        recurring_id = created.json()["id"]
        next_date_before = created.json()["next_date"]
        occurrence_index_before = created.json()["occurrence_index"]

        updated = await client.patch(
            f"/api/recurring/{recurring_id}",
            json={"notes": "just a note"},
            cookies={"walleza_access": cookie},
        )

    assert updated.status_code == 200
    assert updated.json()["next_date"] == next_date_before
    assert updated.json()["occurrence_index"] == occurrence_index_before
    assert updated.json()["notes"] == "just a note"


async def test_client_cannot_send_next_date_at_all_extra_field_ignored(
    seed_user, app_factory
) -> None:
    """No `extra="forbid"` anywhere in this codebase's schemas (matches
    `app.transfers.schemas.TransferCreateIn`'s documented precedent): a
    client-sent `next_date` is silently ignored by Pydantic's default
    "ignore unknown fields" behavior rather than rejected, and the
    server-derived value from `starts_on` persists regardless."""
    owner = seed_user(email="rec-next-date-client-ignored@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "10.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-03-15",
                "next_date": "2099-01-01",
            },
            cookies={"walleza_access": cookie},
        )

    assert created.status_code == 201
    assert created.json()["next_date"] == "2026-03-15"
    assert created.json()["next_date"] != "2099-01-01"
