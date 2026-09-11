"""RED -> GREEN, spec "Workspace-Scoped Access Control" (tasks.md 1.6): a
non-member of workspace W MUST get 404 on list/get/update/delete/apply for
a template belonging to W — mirrors
`tests/transfers/test_transfer_visibility.py`'s non-member coverage
exactly.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_non_member_cannot_get_update_delete_or_apply_another_workspaces_template(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-tpl-owner@example.com")
    non_member = seed_user(email="outsider-tpl@example.com")

    app = app_factory()
    transport = ASGITransport(app=app)
    cookie_w1 = _cookie_for(owner_w1)
    cookie_outsider = _cookie_for(non_member)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie_w1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie_outsider})

        account = await client.post(
            "/api/accounts",
            json={"name": "W1 Checking", "currency": "USD", "is_personal": False},
            cookies={"walleza_access": cookie_w1},
        )
        account_id = account.json()["id"]

        created = await client.post(
            "/api/templates",
            json={
                "name": "Rent",
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
            },
            cookies={"walleza_access": cookie_w1},
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        get_response = await client.get(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie_outsider}
        )
        list_response = await client.get(
            "/api/templates", cookies={"walleza_access": cookie_outsider}
        )
        update_response = await client.patch(
            f"/api/templates/{template_id}",
            json={"notes": "hijacked"},
            cookies={"walleza_access": cookie_outsider},
        )
        delete_response = await client.delete(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie_outsider}
        )
        apply_response = await client.post(
            f"/api/templates/{template_id}/apply",
            json={},
            cookies={"walleza_access": cookie_outsider},
        )
        # The row must be left untouched — the owner can still fetch it.
        owner_view = await client.get(
            f"/api/templates/{template_id}", cookies={"walleza_access": cookie_w1}
        )

    assert get_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == []
    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert apply_response.status_code == 404
    assert owner_view.status_code == 200
