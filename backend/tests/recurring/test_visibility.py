"""RED -> GREEN, spec "Workspace-Scoped Access Control" (tasks.md 1.12): a
non-member of workspace W MUST get 404 on list/get/update/delete for a
recurrence belonging to W — mirrors `tests/templates/test_visibility.py`
exactly.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def test_non_member_cannot_get_update_or_delete_another_workspaces_recurrence(
    seed_user, app_factory
) -> None:
    owner_w1 = seed_user(email="w1-rec-owner@example.com")
    non_member = seed_user(email="outsider-rec@example.com")

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
            "/api/recurring",
            json={
                "account_id": account_id,
                "type": "expense",
                "amount": "100.00",
                "repeat_every": 1,
                "period": "month",
                "starts_on": "2026-01-01",
            },
            cookies={"walleza_access": cookie_w1},
        )
        assert created.status_code == 201
        recurring_id = created.json()["id"]

        get_response = await client.get(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie_outsider}
        )
        list_response = await client.get(
            "/api/recurring", cookies={"walleza_access": cookie_outsider}
        )
        update_response = await client.patch(
            f"/api/recurring/{recurring_id}",
            json={"notes": "hijacked"},
            cookies={"walleza_access": cookie_outsider},
        )
        delete_response = await client.delete(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie_outsider}
        )
        owner_view = await client.get(
            f"/api/recurring/{recurring_id}", cookies={"walleza_access": cookie_w1}
        )

    assert get_response.status_code == 404
    assert list_response.status_code == 200
    assert list_response.json() == []
    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert owner_view.status_code == 200
