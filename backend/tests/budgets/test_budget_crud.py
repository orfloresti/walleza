"""RED -> GREEN, design D66-D70/D73, spec `budget-management`: covers the
create/read/update/delete surface plus its referential and value
validation (tasks.md 1a.5/1a.6).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _bootstrap_category(client: AsyncClient, cookie: str, *, name: str = "Food") -> str:
    response = await client.post(
        "/api/categories",
        json={"name": name, "type": "expense"},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _bootstrap_account(
    client: AsyncClient, cookie: str, *, currency: str = "USD", name: str = "Checking"
) -> str:
    response = await client.post(
        "/api/accounts",
        json={"name": name, "currency": currency},
        cookies={"walleza_access": cookie},
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_create_category_only_budget(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-cat-only@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        response = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["category_id"] == category_id
    assert body["account_id"] is None
    assert body["amount"] == "500.00" or body["amount"] == "500"


async def test_create_account_scoped_budget(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-account-scoped@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)
        account_id = await _bootstrap_account(client, cookie, currency="USD")

        response = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": account_id,
                "amount": "200",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 201
    assert response.json()["account_id"] == account_id


async def test_reject_non_positive_amount(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-non-positive@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        response = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "0", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_reject_invalid_currency_code(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-invalid-currency@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        response = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "10", "currency": "usd"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_reject_invisible_or_nonexistent_category(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-invisible-category@example.com")
    outsider = seed_user(email="budget-outsider-category@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)
    outsider_cookie = _cookie_for(outsider)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await client.get("/api/workspace", cookies={"walleza_access": outsider_cookie})
        foreign_category_id = await _bootstrap_category(client, outsider_cookie)

        response = await client.post(
            "/api/budgets",
            json={"category_id": foreign_category_id, "amount": "10", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        nonexistent_response = await client.post(
            "/api/budgets",
            json={"category_id": str(uuid.uuid4()), "amount": "10", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422
    assert nonexistent_response.status_code == 422


async def test_reject_invisible_or_nonexistent_account(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-invisible-account@example.com")
    outsider = seed_user(email="budget-outsider-account@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)
    outsider_cookie = _cookie_for(outsider)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await client.get("/api/workspace", cookies={"walleza_access": outsider_cookie})
        category_id = await _bootstrap_category(client, cookie)
        foreign_account_id = await _bootstrap_account(client, outsider_cookie)

        response = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": foreign_account_id,
                "amount": "10",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )
        nonexistent_response = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": str(uuid.uuid4()),
                "amount": "10",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422
    assert nonexistent_response.status_code == 422


async def test_account_scoped_budget_currency_mismatch_rejected(seed_user, app_factory) -> None:
    """Design D73: least surprise wins — a mismatched currency would
    otherwise be a silent config error that permanently reports spent=0
    once progress computation lands (unit 1b)."""
    owner = seed_user(email="budget-currency-mismatch@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)
        account_id = await _bootstrap_account(client, cookie, currency="EUR")

        response = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": account_id,
                "amount": "10",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 422


async def test_list_and_get_budget(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-list-get@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

        list_response = await client.get("/api/budgets", cookies={"walleza_access": cookie})
        get_response = await client.get(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": cookie}
        )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert get_response.status_code == 200
    assert get_response.json()["id"] == budget_id


async def test_update_amount(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-update-amount@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

        patched = await client.patch(
            f"/api/budgets/{budget_id}",
            json={"amount": "750"},
            cookies={"walleza_access": cookie},
        )

    assert patched.status_code == 200
    assert patched.json()["amount"] in ("750", "750.00")


async def test_update_rejects_same_validation_as_create(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-update-validation@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

        bad_amount = await client.patch(
            f"/api/budgets/{budget_id}",
            json={"amount": "-1"},
            cookies={"walleza_access": cookie},
        )
        bad_currency = await client.patch(
            f"/api/budgets/{budget_id}",
            json={"currency": "eur"},
            cookies={"walleza_access": cookie},
        )
        unchanged = await client.get(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": cookie}
        )

    assert bad_amount.status_code == 422
    assert bad_currency.status_code == 422
    assert unchanged.json()["amount"] in ("500", "500.00")


async def test_delete_own_budget(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-delete-own@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

        delete_response = await client.delete(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": cookie}
        )
        get_after = await client.get(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 204
    assert get_after.status_code == 404


async def test_cross_workspace_access_denied_on_get_patch_delete(seed_user, app_factory) -> None:
    owner = seed_user(email="budget-xws-owner@example.com")
    outsider = seed_user(email="budget-xws-outsider@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)
    outsider_cookie = _cookie_for(outsider)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        await client.get("/api/workspace", cookies={"walleza_access": outsider_cookie})
        category_id = await _bootstrap_category(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

        get_response = await client.get(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": outsider_cookie}
        )
        patch_response = await client.patch(
            f"/api/budgets/{budget_id}",
            json={"amount": "1"},
            cookies={"walleza_access": outsider_cookie},
        )
        delete_response = await client.delete(
            f"/api/budgets/{budget_id}", cookies={"walleza_access": outsider_cookie}
        )

    assert get_response.status_code == 404
    assert patch_response.status_code == 404
    assert delete_response.status_code == 404


async def test_delete_category_referenced_by_budget_is_blocked_with_widened_message(
    seed_user, app_factory
) -> None:
    """Design D67: `delete_category`'s existing `IntegrityError` handling
    needs no code change — only its message widens to mention budgets."""
    owner = seed_user(email="budget-category-delete-blocked@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)

        await client.post(
            "/api/budgets",
            json={"category_id": category_id, "amount": "500", "currency": "USD"},
            cookies={"walleza_access": cookie},
        )

        delete_response = await client.delete(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )

    assert delete_response.status_code == 409
    assert "budget" in delete_response.json()["detail"]


async def test_deleting_account_cascades_to_its_budgets(
    seed_user, app_factory, db_session
) -> None:
    """Design D68: `account_id` is `ON DELETE CASCADE` — deleting an
    account must delete any budget scoped to it at the database level.
    There is no public delete-account endpoint, so the FK behavior is
    exercised with a direct SQL delete against `app.account`."""
    owner = seed_user(email="budget-account-cascade@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        category_id = await _bootstrap_category(client, cookie)
        account_id = await _bootstrap_account(client, cookie)

        created = await client.post(
            "/api/budgets",
            json={
                "category_id": category_id,
                "account_id": account_id,
                "amount": "500",
                "currency": "USD",
            },
            cookies={"walleza_access": cookie},
        )
        budget_id = created.json()["id"]

    db_session.execute(
        sa.text("DELETE FROM app.account WHERE id = :id"), {"id": uuid.UUID(account_id)}
    )
    db_session.commit()

    remaining = db_session.execute(
        sa.text("SELECT id FROM app.budget WHERE id = :id"), {"id": uuid.UUID(budget_id)}
    ).first()
    assert remaining is None
