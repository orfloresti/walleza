"""RED -> GREEN, spec "Cross-Workspace Account/Category Reference Rejected"
(tasks.md 1.7): `account_id`/`category_id` MUST each independently resolve
inside the caller's own workspace — mirrors
`tests/transactions/test_cross_workspace.py` exactly.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_creating_a_template_with_another_workspaces_account_id_is_rejected(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-tpl-cross@example.com")
    owner_w2 = seed_user(email="w2-tpl-cross@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        w2_account = await client.post(
            "/api/accounts",
            json={"name": "W2 account", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w2},
        )
        w2_account_id = w2_account.json()["id"]

        response = await client.post(
            "/api/templates",
            json={
                "name": "Rent",
                "account_id": w2_account_id,
                "type": "expense",
                "amount": "10.00",
            },
            cookies={"walleza_access": cookie_w1},
        )

    assert response.status_code == 422
    assert "W2 account" not in response.text


async def test_creating_a_template_with_another_workspaces_split_category_is_rejected(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-tpl-split-cross@example.com")
    owner_w2 = seed_user(email="w2-tpl-split-cross@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_w2 = _cookie_for(owner_w2)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w2})

        w1_account = await client.post(
            "/api/accounts",
            json={"name": "W1 account", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w1},
        )
        w1_account_id = w1_account.json()["id"]

        w2_category = await client.post(
            "/api/categories",
            json={"name": "W2 Category", "type": "expense"},
            cookies={"walleza_access": cookie_w2},
        )
        w2_category_id = w2_category.json()["id"]

        response = await client.post(
            "/api/templates",
            json={
                "name": "Rent",
                "account_id": w1_account_id,
                "type": "expense",
                "amount": "10.00",
                "splits": [{"category_id": w2_category_id, "amount": "10.00"}],
            },
            cookies={"walleza_access": cookie_w1},
        )

    assert response.status_code == 422
    assert "W2 Category" not in response.text
