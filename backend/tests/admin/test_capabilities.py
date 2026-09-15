"""RED -> GREEN, Phase 8 Unit 3 (design D109, spec platform-admin domain):
the actual `/api/admin/*` capability endpoints — list users/workspaces/
stats (metadata-only), deactivate/reactivate user and workspace, and
grant/revoke admin including self-revocation (design O6).

Exercises the REAL, fully-wired `app.main.create_app()` app (not a probe
app, unlike `test_deps.py`'s Unit 2 coverage) via the `app_factory`
fixture from `tests/admin/conftest.py`, so these tests also prove the
router is correctly mounted end to end.
"""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token

# Every wire-level key this test proves NEVER appears in any platform-admin
# response body — the "no financial field" negative check (spec "User list
# contains no financial fields" / "Workspace list contains counts, not
# content" scenarios). Deliberately broad: matches the substrings a
# financial field name would contain, not an exhaustive field-name list.
_FORBIDDEN_FINANCIAL_SUBSTRINGS = (
    "balance",
    "amount",
    "transaction",
    "budget_limit",
    "category",
    "currency",
    "account_number",
)


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


async def _client_for(app_factory):
    app = app_factory()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="https://test"), app


def _assert_no_financial_fields(payload: object) -> None:
    text = str(payload).lower()
    for forbidden in _FORBIDDEN_FINANCIAL_SUBSTRINGS:
        assert forbidden not in text, f"response leaked a financial-looking field: {forbidden!r}"


# --- Metadata-only visibility -----------------------------------------------


async def test_list_users_contains_no_financial_fields(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin@example.com")
    grant_platform_admin(user_id=admin_id)
    seed_user(email="plain-user@example.com")
    client, _ = await _client_for(app_factory)

    async with client:
        response = await client.get(
            "/api/admin/users", cookies={"walleza_access": _cookie_for(admin_id)}
        )

    assert response.status_code == 200
    body = response.json()
    emails = {row["email"] for row in body}
    assert {"admin@example.com", "plain-user@example.com"} <= emails
    _assert_no_financial_fields(body)
    allowed_keys = {
        "id", "email", "created_at", "workspace_id", "workspace_name",
        "is_platform_admin", "is_deactivated",
    }
    for row in body:
        assert set(row.keys()) <= allowed_keys


async def test_list_workspaces_contains_counts_not_content(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin2@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = await _client_for(app_factory)

    # Boot the admin's own workspace via the bootstrap route so at least
    # one workspace with one member exists.
    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": _cookie_for(admin_id)})
        response = await client.get(
            "/api/admin/workspaces", cookies={"walleza_access": _cookie_for(admin_id)}
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    _assert_no_financial_fields(body)
    allowed_keys = {"id", "name", "created_at", "member_count", "is_active"}
    for row in body:
        assert set(row.keys()) <= allowed_keys
        assert isinstance(row["member_count"], int)


async def test_stats_endpoint_returns_aggregate_counts(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin3@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = await _client_for(app_factory)

    async with client:
        response = await client.get(
            "/api/admin/stats", cookies={"walleza_access": _cookie_for(admin_id)}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_users"] >= 1
    assert body["total_platform_admins"] >= 1
    _assert_no_financial_fields(body)


# --- Deactivate/reactivate user ---------------------------------------------


async def test_deactivate_then_reactivate_user_round_trips(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin4@example.com")
    grant_platform_admin(user_id=admin_id)
    target_id = seed_user(email="target-user@example.com")
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        deactivate_resp = await client.post(
            f"/api/admin/users/{target_id}/deactivate", cookies=admin_cookie
        )
        list_resp = await client.get("/api/admin/users", cookies=admin_cookie)
        reactivate_resp = await client.post(
            f"/api/admin/users/{target_id}/reactivate", cookies=admin_cookie
        )
        list_resp_2 = await client.get("/api/admin/users", cookies=admin_cookie)

    assert deactivate_resp.status_code == 204
    row = next(r for r in list_resp.json() if r["id"] == str(target_id))
    assert row["is_deactivated"] is True

    assert reactivate_resp.status_code == 204
    row2 = next(r for r in list_resp_2.json() if r["id"] == str(target_id))
    assert row2["is_deactivated"] is False


async def test_deactivate_unknown_user_returns_404(app_factory, seed_user, grant_platform_admin) -> None:
    admin_id = seed_user(email="admin5@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = await _client_for(app_factory)

    async with client:
        response = await client.post(
            f"/api/admin/users/{uuid.uuid4()}/deactivate",
            cookies={"walleza_access": _cookie_for(admin_id)},
        )

    assert response.status_code == 404


# --- Deactivate/reactivate workspace -----------------------------------------


async def test_deactivate_then_reactivate_workspace_round_trips(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin6@example.com")
    grant_platform_admin(user_id=admin_id)
    owner_id = seed_user(email="ws-owner@example.com")
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        get_ws = await client.get(
            "/api/workspace", cookies={"walleza_access": _cookie_for(owner_id)}
        )
        workspace_id = get_ws.json()["id"]

        deactivate_resp = await client.post(
            f"/api/admin/workspaces/{workspace_id}/deactivate", cookies=admin_cookie
        )
        list_resp = await client.get("/api/admin/workspaces", cookies=admin_cookie)
        reactivate_resp = await client.post(
            f"/api/admin/workspaces/{workspace_id}/reactivate", cookies=admin_cookie
        )
        list_resp_2 = await client.get("/api/admin/workspaces", cookies=admin_cookie)

    assert deactivate_resp.status_code == 204
    row = next(r for r in list_resp.json() if r["id"] == workspace_id)
    assert row["is_active"] is False

    assert reactivate_resp.status_code == 204
    row2 = next(r for r in list_resp_2.json() if r["id"] == workspace_id)
    assert row2["is_active"] is True


async def test_deactivate_unknown_workspace_returns_404(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="admin7@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = await _client_for(app_factory)

    async with client:
        response = await client.post(
            f"/api/admin/workspaces/{uuid.uuid4()}/deactivate",
            cookies={"walleza_access": _cookie_for(admin_id)},
        )

    assert response.status_code == 404


# --- Grant/revoke admin (including self-revocation, design O6) -------------


async def test_admin_grants_another_user(app_factory, seed_user, grant_platform_admin) -> None:
    admin_id = seed_user(email="admin8@example.com")
    grant_platform_admin(user_id=admin_id)
    target_id = seed_user(email="future-admin@example.com")
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        grant_resp = await client.post(f"/api/admin/admins/{target_id}", cookies=admin_cookie)
        list_resp = await client.get("/api/admin/users", cookies=admin_cookie)

    assert grant_resp.status_code == 204
    row = next(r for r in list_resp.json() if r["id"] == str(target_id))
    assert row["is_platform_admin"] is True


async def test_grant_admin_twice_returns_409(app_factory, seed_user, grant_platform_admin) -> None:
    admin_id = seed_user(email="admin9@example.com")
    grant_platform_admin(user_id=admin_id)
    target_id = seed_user(email="dupe-admin@example.com")
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        await client.post(f"/api/admin/admins/{target_id}", cookies=admin_cookie)
        second = await client.post(f"/api/admin/admins/{target_id}", cookies=admin_cookie)

    assert second.status_code == 409


async def test_admin_revokes_another_admin(app_factory, seed_user, grant_platform_admin) -> None:
    admin_id = seed_user(email="admin10@example.com")
    grant_platform_admin(user_id=admin_id)
    other_admin_id = seed_user(email="other-admin@example.com")
    grant_platform_admin(user_id=other_admin_id, granted_by=admin_id)
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        revoke_resp = await client.delete(
            f"/api/admin/admins/{other_admin_id}", cookies=admin_cookie
        )
        # revoked admin immediately loses platform-admin authority
        probe = await client.get(
            "/api/admin/users", cookies={"walleza_access": _cookie_for(other_admin_id)}
        )

    assert revoke_resp.status_code == 204
    assert probe.status_code == 403


async def test_self_revocation_allowed_even_as_only_admin(
    app_factory, seed_user, grant_platform_admin
) -> None:
    admin_id = seed_user(email="sole-admin@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        response = await client.delete(f"/api/admin/admins/{admin_id}", cookies=admin_cookie)
        follow_up = await client.get("/api/admin/users", cookies=admin_cookie)

    assert response.status_code == 204
    assert follow_up.status_code == 403


async def test_revoke_non_admin_returns_404(app_factory, seed_user, grant_platform_admin) -> None:
    admin_id = seed_user(email="admin11@example.com")
    grant_platform_admin(user_id=admin_id)
    non_admin_id = seed_user(email="not-an-admin@example.com")
    client, _ = await _client_for(app_factory)
    admin_cookie = {"walleza_access": _cookie_for(admin_id)}

    async with client:
        response = await client.delete(f"/api/admin/admins/{non_admin_id}", cookies=admin_cookie)

    assert response.status_code == 404


# --- Non-admin denied every /api/admin/* route ------------------------------


async def test_non_admin_denied_every_admin_route(app_factory, seed_user) -> None:
    plain_id = seed_user(email="plain@example.com")
    target_id = seed_user(email="target@example.com")
    client, _ = await _client_for(app_factory)
    cookie = {"walleza_access": _cookie_for(plain_id)}

    routes = [
        ("GET", "/api/admin/users"),
        ("GET", "/api/admin/workspaces"),
        ("GET", "/api/admin/stats"),
        ("POST", f"/api/admin/users/{target_id}/deactivate"),
        ("POST", f"/api/admin/users/{target_id}/reactivate"),
        ("POST", f"/api/admin/workspaces/{uuid.uuid4()}/deactivate"),
        ("POST", f"/api/admin/workspaces/{uuid.uuid4()}/reactivate"),
        ("POST", f"/api/admin/admins/{target_id}"),
        ("DELETE", f"/api/admin/admins/{target_id}"),
    ]

    async with client:
        for method, path in routes:
            response = await client.request(method, path, cookies=cookie)
            assert response.status_code == 403, f"{method} {path} did not deny a non-admin"


async def test_unauthenticated_denied_401(app_factory) -> None:
    client, _ = await _client_for(app_factory)

    async with client:
        response = await client.get("/api/admin/users")

    assert response.status_code == 401
