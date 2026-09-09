"""RED -> GREEN, design D29, spec `category-management`'s "Hierarchical
Category CRUD" requirement (tasks.md 2.3):

Category hierarchy is capped at exactly two levels. The DB-level
`ck_category_no_self_parent` CHECK only prevents a direct self-reference
cycle; "a child's parent must itself be top-level" is enforced by
`app.categories.service`'s `_validate_parent_reference`, since expressing
it as a CHECK constraint would require a self-join a CHECK clause cannot
express (design D29's own note). Every violation here is a 422 — the
`parent_id` field is a request BODY input, not a resource fetched by id,
so 404 never applies to it.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_creating_a_child_category_succeeds(seed_user, app_factory) -> None:
    owner = seed_user(email="hierarchy-happy-path@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        parent = await client.post(
            "/api/categories",
            json={"name": "Food", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        assert parent.status_code == 201
        assert parent.json()["parent_id"] is None

        child = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense", "parent_id": parent.json()["id"]},
            cookies={"walleza_access": cookie},
        )

    assert child.status_code == 201
    assert child.json()["parent_id"] == parent.json()["id"]


async def test_creating_a_third_level_category_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="hierarchy-third-level@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        parent = await client.post(
            "/api/categories",
            json={"name": "Food", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        child = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense", "parent_id": parent.json()["id"]},
            cookies={"walleza_access": cookie},
        )
        assert child.status_code == 201

        grandchild = await client.post(
            "/api/categories",
            json={
                "name": "Organic Groceries",
                "type": "expense",
                "parent_id": child.json()["id"],
            },
            cookies={"walleza_access": cookie},
        )

    assert grandchild.status_code == 422


async def test_updating_a_categorys_parent_to_itself_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="hierarchy-self-parent@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        created = await client.post(
            "/api/categories",
            json={"name": "Self Parent", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        category_id = created.json()["id"]

        update_response = await client.patch(
            f"/api/categories/{category_id}",
            json={"parent_id": category_id},
            cookies={"walleza_access": cookie},
        )
        unchanged = await client.get(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie}
        )

    assert update_response.status_code == 422
    assert unchanged.json()["parent_id"] is None


async def test_creating_with_parent_id_from_another_workspace_is_rejected(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="hierarchy-cross-ws-a@example.com")
    owner_b = seed_user(email="hierarchy-cross-ws-b@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_b = _cookie_for(owner_b)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_b})

        a_category = await client.post(
            "/api/categories",
            json={"name": "A's Category", "type": "expense"},
            cookies={"walleza_access": cookie_a},
        )
        assert a_category.status_code == 201

        b_child = await client.post(
            "/api/categories",
            json={
                "name": "B's alleged child",
                "type": "expense",
                "parent_id": a_category.json()["id"],
            },
            cookies={"walleza_access": cookie_b},
        )

    assert b_child.status_code == 422


async def test_reparenting_a_category_with_children_is_rejected(seed_user, app_factory) -> None:
    owner = seed_user(email="hierarchy-reparent-with-children@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = _cookie_for(owner)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})

        top_a = await client.post(
            "/api/categories",
            json={"name": "Top A", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        top_b = await client.post(
            "/api/categories",
            json={"name": "Top B", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
        await client.post(
            "/api/categories",
            json={"name": "Child of A", "type": "expense", "parent_id": top_a.json()["id"]},
            cookies={"walleza_access": cookie},
        )

        # top_a already has a child; making it a child of top_b would
        # create a third hierarchy level from underneath.
        reparent_response = await client.patch(
            f"/api/categories/{top_a.json()['id']}",
            json={"parent_id": top_b.json()["id"]},
            cookies={"walleza_access": cookie},
        )

    assert reparent_response.status_code == 422
