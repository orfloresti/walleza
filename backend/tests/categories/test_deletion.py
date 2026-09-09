"""RED -> GREEN, design D28, spec `category-management`'s "Deletion
Blocked While Children Exist" requirement (tasks.md 2.2):

A category MUST NOT be deleted while it has children, or while it is
still referenced by a `transaction_category_split` row — no cascade, no
silent orphaning. The DB's `ON DELETE RESTRICT` on both
`category.parent_id` and `transaction_category_split.category_id` IS the
enforcement mechanism (design D28); `app.categories.service.delete_category`
only catches the resulting `IntegrityError` and translates it into a
clean 409 — it never reimplements the check. Both the parent-with-children
case and the referenced-by-split case are exercised here as full,
real-Postgres round trips, proving both that the 409 is returned AND that
every row involved survives the attempted deletion unchanged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_deleting_a_parent_with_children_is_rejected_and_rows_survive(
    seed_user, app_factory, categories_db_sessionmaker
) -> None:
    owner = seed_user(email="parent-delete-blocked@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        parent = await client.post(
            "/api/categories",
            json={"name": "Home", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        assert parent.status_code == 201
        parent_id = parent.json()["id"]

        child = await client.post(
            "/api/categories",
            json={"name": "Rent", "type": "expense", "parent_id": parent_id},
            cookies={"walleza_access": cookie},
        )
        assert child.status_code == 201
        child_id = child.json()["id"]

        delete_response = await client.delete(
            f"/api/categories/{parent_id}", cookies={"walleza_access": cookie}
        )

        # The parent's row is untouched — still fetchable through the API,
        # not just surviving at the raw-SQL layer.
        parent_still_there = await client.get(
            f"/api/categories/{parent_id}", cookies={"walleza_access": cookie}
        )
        child_still_there = await client.get(
            f"/api/categories/{child_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 409
    assert parent_still_there.status_code == 200
    assert parent_still_there.json()["name"] == "Home"
    assert child_still_there.status_code == 200
    assert child_still_there.json()["parent_id"] == parent_id

    with categories_db_sessionmaker() as session:
        rows = session.execute(
            sa.text("SELECT id FROM app.category WHERE id IN (:parent_id, :child_id)"),
            {"parent_id": parent_id, "child_id": child_id},
        ).all()
    assert {str(row.id) for row in rows} == {parent_id, child_id}, (
        "both parent and child rows must survive a blocked deletion attempt"
    )


async def test_deleting_a_childless_category_succeeds(seed_user, app_factory) -> None:
    owner = seed_user(email="childless-delete@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        created = await client.post(
            "/api/categories",
            json={"name": "One-off", "type": "income"},
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        category_id = created.json()["id"]

        delete_response = await client.delete(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )
        get_after = await client.get(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert get_after.status_code == 404


async def test_deleting_a_category_referenced_by_a_transaction_split_is_rejected(
    seed_user, app_factory, categories_db_sessionmaker
) -> None:
    """Transactions CRUD does not exist yet (PR3/PR3b) — the split row is
    seeded directly against the same real Postgres via raw SQL, exactly
    as `seed_user` seeds `app_user` rows out-of-band. The category's
    deletion path is exercised through the real API, proving the FK
    `ON DELETE RESTRICT` on `transaction_category_split.category_id`
    blocks it exactly like the parent/child case above."""
    owner = seed_user(email="split-delete-blocked@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        workspace_id = workspace.json()["id"]

        created = await client.post(
            "/api/categories",
            json={"name": "Referenced", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        category_id = created.json()["id"]

        account_id = uuid.uuid4()
        transaction_id = uuid.uuid4()
        split_id = uuid.uuid4()
        with categories_db_sessionmaker() as session:
            session.execute(
                sa.text(
                    "INSERT INTO app.account "
                    "(id, workspace_id, owner_user_id, name, currency, exchange_rate, "
                    "initial_funds, is_personal, archived, created_at, updated_at) "
                    "VALUES (:id, :workspace_id, NULL, 'Checking', 'USD', 1, 0, false, "
                    "false, now(), now())"
                ),
                {"id": account_id, "workspace_id": workspace_id},
            )
            session.execute(
                sa.text(
                    "INSERT INTO app.transaction "
                    "(id, workspace_id, account_id, type, amount, occurred_on, "
                    "is_refund, checked, created_at, updated_at) "
                    "VALUES (:id, :workspace_id, :account_id, 'expense', 42.00, "
                    ":occurred_on, false, false, now(), now())"
                ),
                {
                    "id": transaction_id,
                    "workspace_id": workspace_id,
                    "account_id": account_id,
                    "occurred_on": datetime.now(UTC).date(),
                },
            )
            session.execute(
                sa.text(
                    "INSERT INTO app.transaction_category_split "
                    "(id, transaction_id, category_id, amount) "
                    "VALUES (:id, :transaction_id, :category_id, 42.00)"
                ),
                {
                    "id": split_id,
                    "transaction_id": transaction_id,
                    "category_id": category_id,
                },
            )
            session.commit()

        delete_response = await client.delete(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )
        get_after = await client.get(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 409
    assert get_after.status_code == 200

    with categories_db_sessionmaker() as session:
        category_row = session.execute(
            sa.text("SELECT id FROM app.category WHERE id = :id"), {"id": category_id}
        ).first()
        split_row = session.execute(
            sa.text("SELECT id FROM app.transaction_category_split WHERE id = :id"),
            {"id": split_id},
        ).first()
    assert category_row is not None, "category must survive a blocked deletion attempt"
    assert split_row is not None, "the referencing split row must be untouched"
