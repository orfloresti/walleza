"""RED -> GREEN, decision 6 / design D16, spec RED #8 (tasks.md 5.3):

Archiving an account excludes it from the DEFAULT account list and from
`/api/workspace/summary` totals, but never deletes the row: it is still
retrievable with `?archived=true` and still SELECTable directly against
the database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_archiving_excludes_from_default_list_and_summary_but_retains_row(
    seed_user, app_factory, accounts_db_sessionmaker
) -> None:
    user_id = seed_user(email="archiver@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(user_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        created = await client.post(
            "/api/accounts",
            json={
                "name": "To be archived",
                "currency": "USD",
                "initial_funds": "500.00",
                "is_personal": False,
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        account_id = created.json()["id"]

        before_summary = await client.get(
            "/api/workspace/summary", cookies={"walleza_access": cookie}
        )
        before_total = next(
            row for row in before_summary.json()["by_currency"] if row["currency"] == "USD"
        )["total"]
        assert Decimal(before_total) == Decimal("500.00")

        archived_response = await client.patch(
            f"/api/accounts/{account_id}",
            json={"archived": True},
            cookies={"walleza_access": cookie},
        )
        assert archived_response.status_code == 200
        assert archived_response.json()["archived"] is True

        default_list = await client.get("/api/accounts", cookies={"walleza_access": cookie})
        archived_list = await client.get(
            "/api/accounts", params={"archived": "true"}, cookies={"walleza_access": cookie}
        )
        after_summary = await client.get(
            "/api/workspace/summary", cookies={"walleza_access": cookie}
        )

    assert all(row["id"] != account_id for row in default_list.json())
    assert any(row["id"] == account_id for row in archived_list.json())
    assert archived_list.json()[0]["archived"] is True

    # Excluded from totals (design D16: summary filters `archived=false`).
    assert after_summary.json()["by_currency"] == []
    assert Decimal(after_summary.json()["grand_total"]) == Decimal(0)

    with accounts_db_sessionmaker() as session:
        row = session.execute(
            sa.text("SELECT archived, name FROM app.account WHERE id = :id"), {"id": account_id}
        ).first()
    assert row is not None, "archiving must not delete the row"
    assert row.archived is True
    assert row.name == "To be archived"
