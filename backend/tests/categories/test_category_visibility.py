"""RED -> GREEN, design D18/D30, spec `category-management`'s
"Workspace-Scoped Access Control" requirement (tasks.md 2.1):

A user who is not a member of workspace W (i.e. has their own, separate
workspace and never joined W via invite) must be rejected with 404 on
every direct-id category read/write path, and must never see W's
categories in their own list — mirroring
`tests/accounts/test_visibility.py`'s exact D18 pattern. Categories have
no personal/visibility flag (decision #7), so the relevant boundary here
is strictly cross-workspace, not cross-member-within-a-workspace.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_non_member_cannot_get_patch_or_delete_a_foreign_workspaces_category(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-cat-visibility@example.com")
    outsider_c = seed_user(email="c-cat-visibility@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_c = _cookie_for(outsider_c)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_c})

        created = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense"},
            cookies={"walleza_access": cookie_a},
        )
        assert created.status_code == 201
        category_id = created.json()["id"]

        get_response = await client.get(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie_c}
        )
        patch_response = await client.patch(
            f"/api/categories/{category_id}",
            json={"name": "renamed"},
            cookies={"walleza_access": cookie_c},
        )
        delete_response = await client.delete(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie_c}
        )

        # The owner's OWN view must still work — proves the 404s above are
        # a visibility boundary, not a broken route.
        owner_view = await client.get(
            f"/api/categories/{category_id}", cookies={"walleza_access": cookie_a}
        )

    assert get_response.status_code == 404
    assert "Groceries" not in get_response.text
    assert patch_response.status_code == 404
    assert "Groceries" not in patch_response.text
    assert delete_response.status_code == 404
    assert "Groceries" not in delete_response.text

    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == "Groceries"


async def test_non_member_does_not_see_foreign_workspaces_category_in_list(
    seed_user, app_factory
) -> None:
    owner_a = seed_user(email="a-cat-list@example.com")
    outsider_c = seed_user(email="c-cat-list@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_c = _cookie_for(outsider_c)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_c})

        await client.post(
            "/api/categories",
            json={"name": "A's Rent", "type": "expense"},
            cookies={"walleza_access": cookie_a},
        )
        await client.post(
            "/api/categories",
            json={"name": "C's Rent", "type": "expense"},
            cookies={"walleza_access": cookie_c},
        )

        list_as_c = await client.get("/api/categories", cookies={"walleza_access": cookie_c})
        list_as_a = await client.get("/api/categories", cookies={"walleza_access": cookie_a})

    names_c = {row["name"] for row in list_as_c.json()}
    names_a = {row["name"] for row in list_as_a.json()}
    assert names_c == {"C's Rent"}
    assert names_a == {"A's Rent"}


async def test_non_member_cannot_create_or_have_it_attributed_to_another_workspace(
    seed_user, app_factory
) -> None:
    """There is no `workspace_id` field on the create payload — every
    create is scoped to the CALLER's own workspace, never an arbitrary
    target. This test proves that structurally: two unrelated users each
    create a category with the identical name, and each only ever sees
    their own row, never the other's."""
    owner_a = seed_user(email="a-cat-create@example.com")
    outsider_c = seed_user(email="c-cat-create@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_a = _cookie_for(owner_a)
    cookie_c = _cookie_for(outsider_c)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_a})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_c})

        created_a = await client.post(
            "/api/categories",
            json={"name": "Utilities", "type": "expense"},
            cookies={"walleza_access": cookie_a},
        )
        created_c = await client.post(
            "/api/categories",
            json={"name": "Utilities", "type": "expense"},
            cookies={"walleza_access": cookie_c},
        )
        assert created_a.status_code == 201
        assert created_c.status_code == 201
        assert created_a.json()["id"] != created_c.json()["id"]
        assert created_a.json()["workspace_id"] != created_c.json()["workspace_id"]

        get_as_c = await client.get(
            f"/api/categories/{created_a.json()['id']}", cookies={"walleza_access": cookie_c}
        )

    assert get_as_c.status_code == 404
