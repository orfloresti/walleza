"""RED -> GREEN, spec "Apply Creates a Real Transaction, Template Stays
Reusable" (R8, tasks.md 1.9) and "Applying a Template With a Stale
Reference Fails Cleanly" (tasks.md 1.10). Every scenario here proves
`apply_template` reuses `transactions.service.create_transaction`/
`replace_splits` VERBATIM — no bespoke validation exists in the apply path
itself.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _create_account(client, cookie: str, *, name: str = "Checking") -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": "USD", "is_personal": False},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_category(client, cookie: str, *, name: str) -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_applying_twice_creates_two_independent_transactions_template_unchanged(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="tpl-apply-twice@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/templates",
            json={
                "name": "Coffee",
                "account_id": account_id,
                "type": "expense",
                "amount": "5.00",
                "notes": "daily coffee",
            },
            cookies={"walleza_access": cookie},
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        first_apply = await client.post(
            f"/api/templates/{template_id}/apply",
            json={"occurred_on": "2026-01-10"},
            cookies={"walleza_access": cookie},
        )
        second_apply = await client.post(
            f"/api/templates/{template_id}/apply",
            json={"occurred_on": "2026-01-11"},
            cookies={"walleza_access": cookie},
        )

        template_after = await client.get(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie}
        )

    assert first_apply.status_code == 201
    assert second_apply.status_code == 201
    assert first_apply.json()["id"] != second_apply.json()["id"]
    assert Decimal(first_apply.json()["amount"]) == Decimal("5.00")
    assert first_apply.json()["account_id"] == account_id
    assert first_apply.json()["notes"] == "daily coffee"
    assert first_apply.json()["occurred_on"] == "2026-01-10"
    assert second_apply.json()["occurred_on"] == "2026-01-11"
    # is_refund/checked always False for a generated row (R7/design D56).
    assert first_apply.json()["is_refund"] is False
    assert first_apply.json()["checked"] is False
    # The template row itself is byte-identically unchanged.
    assert template_after.json()["name"] == "Coffee"
    assert Decimal(template_after.json()["amount"]) == Decimal("5.00")


async def test_apply_with_no_override_defaults_occurred_on_to_today(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="tpl-apply-today@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/templates",
            json={"name": "Coffee", "account_id": account_id, "type": "expense", "amount": "5.00"},
            cookies={"walleza_access": cookie},
        )
        template_id = created.json()["id"]

        applied = await client.post(
            f"/api/templates/{template_id}/apply",
            json={},
            cookies={"walleza_access": cookie},
        )

    assert applied.status_code == 201
    assert applied.json()["occurred_on"] is not None


async def test_template_with_splits_applies_with_all_splits_intact(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="tpl-apply-splits@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)
        category_a = await _create_category(client, cookie, name="Rent")
        category_b = await _create_category(client, cookie, name="Utilities")

        created = await client.post(
            "/api/templates",
            json={
                "name": "Rent+Utilities",
                "account_id": account_id,
                "type": "expense",
                "amount": "150.00",
                "splits": [
                    {"category_id": category_a, "amount": "100.00"},
                    {"category_id": category_b, "amount": "50.00"},
                ],
            },
            cookies={"walleza_access": cookie},
        )
        template_id = created.json()["id"]

        applied = await client.post(
            f"/api/templates/{template_id}/apply",
            json={"occurred_on": "2026-02-01"},
            cookies={"walleza_access": cookie},
        )

    assert applied.status_code == 201
    splits = applied.json()["splits"]
    assert len(splits) == 2
    total = sum(Decimal(s["amount"]) for s in splits)
    assert total == Decimal("150.00")


async def test_applying_a_template_whose_split_category_is_stale_fails_cleanly(
    seed_user, app_factory, db_session
) -> None:
    """Simulates "the category is no longer a valid reference at apply
    time" (spec: "a template's category_id no longer resolves") via direct
    SQL: the split's `category_id` is repointed at a category belonging to
    a DIFFERENT workspace, bypassing the normal create/update-time
    validation entirely. This satisfies the FK (the category row genuinely
    exists — `ON DELETE RESTRICT` would otherwise block an actual delete
    while any split still references it) while reproducing the exact
    failure mode `replace_splits`'s `visible_categories(scope)` check
    exists to catch: a reference invisible to the caller's own workspace.
    Apply MUST fail with 422 and create nothing — no crash, no partial
    transaction."""
    owner = seed_user(email="tpl-apply-stale-category@example.com")
    other = seed_user(email="tpl-apply-stale-other@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)
    other_cookie = _cookie_for(other)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        other_ws = await client.get(
            "/api/workspace", cookies={"walleza_access": other_cookie}
        )
        account_id = await _create_account(client, cookie)
        category_id = await _create_category(client, cookie, name="Temp Category")
        other_category = await client.post(
            "/api/categories",
            json={"name": "Foreign Category", "type": "expense"},
            cookies={"walleza_access": other_cookie},
        )
        foreign_category_id = other_category.json()["id"]
        assert other_ws.status_code == 200

        created = await client.post(
            "/api/templates",
            json={
                "name": "One Category",
                "account_id": account_id,
                "type": "expense",
                "amount": "20.00",
                "splits": [{"category_id": category_id, "amount": "20.00"}],
            },
            cookies={"walleza_access": cookie},
        )
        template_id = created.json()["id"]

        db_session.execute(
            sa.text(
                "UPDATE app.transaction_template_split SET category_id = :foreign "
                "WHERE template_id = :template_id"
            ),
            {"foreign": foreign_category_id, "template_id": template_id},
        )
        db_session.commit()

        transactions_before = db_session.execute(
            sa.text("SELECT count(*) FROM app.transaction")
        ).scalar_one()

        applied = await client.post(
            f"/api/templates/{template_id}/apply",
            json={"occurred_on": "2026-02-01"},
            cookies={"walleza_access": cookie},
        )

        transactions_after = db_session.execute(
            sa.text("SELECT count(*) FROM app.transaction")
        ).scalar_one()

    assert applied.status_code == 422
    assert transactions_after == transactions_before


async def test_applying_a_template_against_an_archived_account_succeeds(
    seed_user, app_factory
) -> None:
    owner = seed_user(email="tpl-apply-archived-account@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        account_id = await _create_account(client, cookie)

        created = await client.post(
            "/api/templates",
            json={
                "name": "Old Account Template",
                "account_id": account_id,
                "type": "expense",
                "amount": "20.00",
            },
            cookies={"walleza_access": cookie},
        )
        template_id = created.json()["id"]

        archive_account = await client.patch(
            f"/api/accounts/{account_id}",
            json={"archived": True},
            cookies={"walleza_access": cookie},
        )
        assert archive_account.status_code == 200
        assert archive_account.json()["archived"] is True

        applied = await client.post(
            f"/api/templates/{template_id}/apply",
            json={"occurred_on": "2026-02-01"},
            cookies={"walleza_access": cookie},
        )

    assert applied.status_code == 201
    assert applied.json()["account_id"] == account_id
