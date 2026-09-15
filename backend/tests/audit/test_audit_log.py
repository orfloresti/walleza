"""RED -> GREEN, Phase 8 Unit 5 (design D102-D105, spec audit-log domain):
the 11 spec scenarios for privileged-action-only logging, append-only
storage, and scoped read access.

Exercises the REAL, fully-wired `app.main.create_app()` app via the
`app_factory` fixture from `tests/audit/conftest.py`, mirroring
`tests/admin/test_capabilities.py`'s end-to-end style.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _client_for(app_factory) -> tuple[AsyncClient, object]:
    app = app_factory()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="https://test"), app


def _audit_rows(audit_db_sessionmaker, *, actor_user_id: uuid.UUID | None = None) -> list[dict]:
    """Reads the full `audit_log` table, optionally filtered to one actor.

    `audit_db_sessionmaker` is module-scoped (a real, shared ephemeral
    Postgres for the whole test module — matching every other real-Postgres
    fixture in this repo), so tests that assert an EXACT row count filter
    by `actor_user_id` to isolate their own writes from earlier tests in
    the same module, rather than asserting on the whole table."""
    with audit_db_sessionmaker() as session:
        query = (
            "SELECT id, actor_user_id, actor_was_platform_admin, action, "
            "target_type, target_id, workspace_id, metadata FROM app.audit_log"
        )
        params: dict[str, object] = {}
        if actor_user_id is not None:
            query += " WHERE actor_user_id = :actor_user_id"
            params["actor_user_id"] = actor_user_id
        query += " ORDER BY created_at"
        rows = session.execute(sa.text(query), params).mappings().all()
        return [dict(row) for row in rows]


# --- Privileged-action-only logging -----------------------------------------


async def test_owner_action_logged(seed_user, app_factory, audit_db_sessionmaker) -> None:
    owner_id = seed_user(email="owner-audit@example.com")
    client, _ = _client_for(app_factory)
    cookie = _cookie_for(owner_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.patch(
            "/api/workspace", json={"name": "Renamed WS"}, cookies={"walleza_access": cookie}
        )
    assert response.status_code == 200

    rows = _audit_rows(audit_db_sessionmaker, actor_user_id=owner_id)
    assert len(rows) == 1
    assert rows[0]["action"] == "workspace.renamed"
    assert rows[0]["actor_user_id"] == owner_id
    assert rows[0]["actor_was_platform_admin"] is False


async def test_platform_admin_action_logged(
    seed_user, grant_platform_admin, app_factory, audit_db_sessionmaker
) -> None:
    admin_id = seed_user(email="admin-audit@example.com")
    target_id = seed_user(email="target-audit@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = _client_for(app_factory)

    async with client:
        response = await client.post(
            f"/api/admin/users/{target_id}/deactivate",
            cookies={"walleza_access": _cookie_for(admin_id)},
        )
    assert response.status_code == 204

    rows = _audit_rows(audit_db_sessionmaker, actor_user_id=admin_id)
    assert len(rows) == 1
    assert rows[0]["action"] == "platform.user_deactivated"
    assert rows[0]["actor_user_id"] == admin_id
    assert rows[0]["actor_was_platform_admin"] is True
    assert rows[0]["target_id"] == target_id
    assert rows[0]["workspace_id"] is None


async def test_ordinary_crud_never_audited(seed_user, app_factory, audit_db_sessionmaker) -> None:
    user_id = seed_user(email="crud-audit@example.com")
    client, _ = _client_for(app_factory)
    cookie = _cookie_for(user_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie})
        response = await client.post(
            "/api/categories",
            json={"name": "Groceries", "type": "expense"},
            cookies={"walleza_access": cookie},
        )
    assert response.status_code == 201
    assert _audit_rows(audit_db_sessionmaker, actor_user_id=user_id) == []


async def test_self_removal_not_audited(seed_user, app_factory, audit_db_sessionmaker) -> None:
    owner_id = seed_user(email="owner-self-leave@example.com")
    peer_id = seed_user(email="peer-self-leave@example.com")
    client, _ = _client_for(app_factory)
    owner_cookie = _cookie_for(owner_id)
    peer_cookie = _cookie_for(peer_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": peer_cookie})
        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        token = invite.json()["url"].rsplit("/", 1)[-1]
        await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": peer_cookie},
        )
        response = await client.delete(
            "/api/workspace/members/me", cookies={"walleza_access": peer_cookie}
        )
    assert response.status_code == 204

    rows = _audit_rows(audit_db_sessionmaker, actor_user_id=peer_id)
    assert rows == []


# --- Append-only storage -----------------------------------------------------


def test_no_update_or_delete_path_exists_for_audit_log() -> None:
    import ast
    from pathlib import Path

    import app as app_package

    app_root = Path(app_package.__file__).resolve().parent
    offenders: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        source = path.read_text()
        if "AuditLog" not in source:
            continue
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"update", "delete"}
            ):
                # sa.update(AuditLog) / sa.delete(AuditLog) — detect by any
                # argument referencing the `AuditLog` name.
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id == "AuditLog":
                        offenders.append(str(path.relative_to(app_root.parent)))
    assert offenders == [], f"found an update/delete path targeting AuditLog: {offenders}"


# --- Scoped read access ------------------------------------------------------


async def test_owner_reads_own_workspace_rows_only(seed_user, app_factory) -> None:
    owner1_id = seed_user(email="owner1-scoped@example.com")
    owner2_id = seed_user(email="owner2-scoped@example.com")
    client, _ = _client_for(app_factory)
    cookie1 = _cookie_for(owner1_id)
    cookie2 = _cookie_for(owner2_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": cookie1})
        await client.get("/api/workspace", cookies={"walleza_access": cookie2})
        await client.patch(
            "/api/workspace", json={"name": "WS1"}, cookies={"walleza_access": cookie1}
        )
        await client.patch(
            "/api/workspace", json={"name": "WS2"}, cookies={"walleza_access": cookie2}
        )
        response = await client.get("/api/workspace/audit", cookies={"walleza_access": cookie1})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["action"] == "workspace.renamed"
    assert body[0]["metadata"]["name"] == "WS1"


async def test_owner_sees_platform_admin_action_on_own_workspace(
    seed_user, grant_platform_admin, app_factory
) -> None:
    owner_id = seed_user(email="owner-o3@example.com")
    admin_id = seed_user(email="admin-o3@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = _client_for(app_factory)
    owner_cookie = _cookie_for(owner_id)
    admin_cookie = _cookie_for(admin_id)

    async with client:
        owner_ws = await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        workspace_id = owner_ws.json()["id"]

        deactivate = await client.post(
            f"/api/admin/workspaces/{workspace_id}/deactivate",
            cookies={"walleza_access": admin_cookie},
        )
        assert deactivate.status_code == 204

        response = await client.get(
            "/api/workspace/audit", cookies={"walleza_access": owner_cookie}
        )

    assert response.status_code == 200
    body = response.json()
    assert any(row["action"] == "platform.workspace_deactivated" for row in body)


async def test_owner_cannot_see_platform_admin_action_on_another_workspace(
    seed_user, grant_platform_admin, app_factory
) -> None:
    owner1_id = seed_user(email="owner1-o3neg@example.com")
    owner2_id = seed_user(email="owner2-o3neg@example.com")
    admin_id = seed_user(email="admin-o3neg@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = _client_for(app_factory)
    owner1_cookie = _cookie_for(owner1_id)
    owner2_cookie = _cookie_for(owner2_id)
    admin_cookie = _cookie_for(admin_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": owner1_cookie})
        owner2_ws = await client.get("/api/workspace", cookies={"walleza_access": owner2_cookie})
        workspace2_id = owner2_ws.json()["id"]

        await client.post(
            f"/api/admin/workspaces/{workspace2_id}/deactivate",
            cookies={"walleza_access": admin_cookie},
        )

        response = await client.get(
            "/api/workspace/audit", cookies={"walleza_access": owner1_cookie}
        )

    assert response.status_code == 200
    body = response.json()
    assert body == []


async def test_plain_member_denied_audit_read(seed_user, app_factory) -> None:
    owner_id = seed_user(email="owner-member-denied@example.com")
    peer_id = seed_user(email="peer-member-denied@example.com")
    client, _ = _client_for(app_factory)
    owner_cookie = _cookie_for(owner_id)
    peer_cookie = _cookie_for(peer_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.get("/api/workspace", cookies={"walleza_access": peer_cookie})
        invite = await client.post(
            "/api/workspace/invites", cookies={"walleza_access": owner_cookie}
        )
        token = invite.json()["url"].rsplit("/", 1)[-1]
        await client.post(
            "/api/workspace/invites/accept",
            json={"token": token},
            cookies={"walleza_access": peer_cookie},
        )
        response = await client.get(
            "/api/workspace/audit", cookies={"walleza_access": peer_cookie}
        )

    assert response.status_code == 403


async def test_platform_admin_reads_all_rows(
    seed_user, grant_platform_admin, app_factory
) -> None:
    admin_id = seed_user(email="admin-readall@example.com")
    owner_id = seed_user(email="owner-readall@example.com")
    grant_platform_admin(user_id=admin_id)
    client, _ = _client_for(app_factory)
    admin_cookie = _cookie_for(admin_id)
    owner_cookie = _cookie_for(owner_id)

    async with client:
        await client.get("/api/workspace", cookies={"walleza_access": owner_cookie})
        await client.patch(
            "/api/workspace", json={"name": "Renamed"}, cookies={"walleza_access": owner_cookie}
        )
        target_id = seed_user(email="admin-readall-target@example.com")
        await client.post(
            f"/api/admin/users/{target_id}/deactivate",
            cookies={"walleza_access": admin_cookie},
        )

        response = await client.get("/api/admin/audit", cookies={"walleza_access": admin_cookie})

    assert response.status_code == 200
    body = response.json()
    actions = {row["action"] for row in body}
    assert {"workspace.renamed", "platform.user_deactivated"} <= actions


# --- Atomicity ---------------------------------------------------------------


def test_audit_write_rolls_back_with_failed_transaction(audit_db_sessionmaker, seed_user) -> None:
    """Spec "Audit write and mutation are atomic" scenario: `record_audit`
    only ever `flush()`es, never `commit()`s, so a later failure in the
    SAME transaction rolls the audit row back with it."""
    from app.audit.actions import AuditAction
    from app.audit.service import record_audit

    owner_id = seed_user(email="atomic-audit@example.com")

    session = audit_db_sessionmaker()
    try:
        record_audit(
            session,
            actor_user_id=owner_id,
            actor_was_platform_admin=False,
            action=AuditAction.WORKSPACE_RENAMED,
            target_type="workspace",
            target_id=None,
            workspace_id=None,
        )
        # Force a later failure in the SAME transaction (a bogus FK target).
        try:
            session.execute(
                sa.text(
                    "INSERT INTO app.workspace_member "
                    "(id, workspace_id, user_id, joined_at) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), now())"
                )
            )
            session.flush()
        except sa.exc.DBAPIError:
            session.rollback()
        else:
            session.rollback()
            raise AssertionError("expected the bogus FK insert to fail")
    finally:
        session.close()

    with audit_db_sessionmaker() as verify_session:
        count = verify_session.execute(
            sa.text("SELECT count(*) FROM app.audit_log WHERE actor_user_id = :actor"),
            {"actor": owner_id},
        ).scalar_one()
    assert count == 0
