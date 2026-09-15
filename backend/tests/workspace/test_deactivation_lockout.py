"""Phase 8 design D106 / Unit 4 task 4.3: the read-only lockout enforced
inside `require_membership` (`app/deps.py`).

Matrix strategy: one representative GET and one representative mutation
per workspace-scoped route family (accounts, categories, transactions,
transfers, templates, recurring, budgets, reports, workspace itself),
plus the reactivation path. This is not exhaustive per-route — every
family shares the exact same `require_membership` gate
(`test_route_coverage.py` proves that exhaustively), so one representative
pair per family is sufficient to prove the lockout composes correctly
with each family's own dependency wiring, without re-testing
`require_membership`'s core logic ~30 times.

Mutation requests are sent with an empty/minimal JSON body. This is
deliberate, not an oversight: `require_membership` is a ROUTER-level
dependency (`APIRouter(dependencies=[Depends(require_membership)])`), so
FastAPI resolves it before parsing/validating the request body — the 403
from a deactivated workspace fires regardless of body shape. Body
validity is exercised elsewhere by each family's own tests.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


async def _bootstrap(client: AsyncClient, cookie: str) -> uuid.UUID:
    """GET /api/workspace, the bootstrap get-or-create route, establishes
    membership (as owner, since this is the workspace's first member) and
    returns the workspace id."""
    response = await client.get("/api/workspace", cookies={"walleza_access": cookie})
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"])


def _set_active(db_session, *, workspace_id: uuid.UUID, active: bool) -> None:
    db_session.execute(
        sa.text("UPDATE app.workspace SET is_active = :active WHERE id = :id"),
        {"active": active, "id": workspace_id},
    )
    db_session.commit()


async def test_deactivated_workspace_matrix(
    seed_user, app_factory, db_session
) -> None:
    user_id = seed_user(email="lockout-owner@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id = await _bootstrap(client, cookie)
        _set_active(db_session, workspace_id=workspace_id, active=False)

        # GET-shaped requests pass through for every family.
        get_cases = [
            "/api/accounts",
            "/api/categories",
            "/api/transactions",
            "/api/transfers",
            "/api/templates",
            "/api/recurring",
            "/api/budgets",
            "/api/reports/default-currency",
            "/api/workspace/summary",
            "/api/workspace/invites",
        ]
        for path in get_cases:
            response = await client.get(path, cookies={"walleza_access": cookie})
            assert response.status_code == 200, f"GET {path} should pass through, got {response.status_code}"

        # Mutating requests are rejected with 403 for every family.
        mutation_cases = [
            ("POST", "/api/accounts"),
            ("POST", "/api/categories"),
            ("POST", "/api/transactions"),
            ("POST", "/api/transfers"),
            ("POST", "/api/templates"),
            ("POST", "/api/recurring"),
            ("POST", "/api/budgets"),
            ("PATCH", "/api/workspace"),
            ("POST", "/api/workspace/invites"),
            ("DELETE", "/api/workspace/members/me"),
        ]
        for method, path in mutation_cases:
            response = await client.request(
                method, path, json={}, cookies={"walleza_access": cookie}
            )
            assert response.status_code == 403, (
                f"{method} {path} should be blocked on a deactivated workspace, "
                f"got {response.status_code}"
            )
            assert "workspace is deactivated" in response.text


async def test_reactivation_restores_mutation_ability(
    seed_user, app_factory, db_session
) -> None:
    user_id = seed_user(email="lockout-reactivate@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id = await _bootstrap(client, cookie)
        _set_active(db_session, workspace_id=workspace_id, active=False)

        blocked = await client.post("/api/accounts", json={}, cookies={"walleza_access": cookie})
        assert blocked.status_code == 403

        _set_active(db_session, workspace_id=workspace_id, active=True)

        restored = await client.post(
            "/api/accounts",
            json={
                "name": "Checking",
                "currency": "USD",
                "exchange_rate": "1",
                "initial_funds": "0",
                "is_personal": True,
            },
            cookies={"walleza_access": cookie},
        )
        assert restored.status_code == 201

        # Owner-only mutation (layered `require_owner`) also composes
        # correctly once reactivated.
        renamed = await client.patch(
            "/api/workspace", json={"name": "Reactivated Workspace"}, cookies={"walleza_access": cookie}
        )
        assert renamed.status_code == 200


async def test_get_workspace_bootstrap_stays_reachable_when_deactivated(
    seed_user, app_factory, db_session
) -> None:
    """`GET /api/workspace` is not behind `require_membership` at all
    (design D13/D106) — it must stay reachable so a member of a locked
    workspace can still see their workspace shell."""
    user_id = seed_user(email="lockout-bootstrap@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id = await _bootstrap(client, cookie)
        _set_active(db_session, workspace_id=workspace_id, active=False)

        response = await client.get("/api/workspace", cookies={"walleza_access": cookie})

    assert response.status_code == 200


async def test_invite_accept_is_blocked_for_a_deactivated_workspace(
    seed_user, app_factory, db_session
) -> None:
    """Design D106's documented consequence: `POST
    /api/workspace/invites/accept` is a mutating, `require_membership`-gated
    route, so it is blocked for a member of a deactivated workspace even
    though it targets a DIFFERENT workspace's invite — the check is on the
    caller's OWN membership row, evaluated before the invite is even
    looked up."""
    user_id = seed_user(email="lockout-accept@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        workspace_id = await _bootstrap(client, cookie)
        _set_active(db_session, workspace_id=workspace_id, active=False)

        response = await client.post(
            "/api/workspace/invites/accept",
            json={"token": "does-not-matter"},
            cookies={"walleza_access": cookie},
        )

    assert response.status_code == 403
