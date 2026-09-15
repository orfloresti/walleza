"""RED -> GREEN, Phase 8 design D98, tasks.md Unit 2 task 2.3:
`require_platform_admin` resolves a `PlatformAdminContext` for a granted
admin, 403s for a non-admin, and 401s for an unauthenticated caller —
re-reading the `platform_admin` table on every request rather than
trusting anything on the JWT.

This Unit ships no admin capability route (design's own note: "no admin
capability route exists yet to distract review"), so this test exercises
`require_platform_admin` end-to-end through one minimal, test-local route
mounted directly on a fresh `FastAPI()` instance — not through
`app.main.create_app()` — proving the dependency wiring itself works
without adding a real route to the shipped app ahead of Unit 3.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.admin.deps import PlatformAdminContext, require_platform_admin
from app.db import get_db
from app.security import issue_access_token


def _cookie_for(user_id: uuid.UUID) -> str:
    return issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))


def _probe_app(admin_db_sessionmaker) -> FastAPI:
    app = FastAPI()

    @app.get("/probe/admin-only")
    def admin_only(ctx: PlatformAdminContext = Depends(require_platform_admin)) -> dict[str, str]:
        return {"user_id": str(ctx.user_id)}

    def override_get_db():
        session = admin_db_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    return app


async def test_granted_admin_resolves_context(
    seed_user, grant_platform_admin, admin_db_sessionmaker
) -> None:
    user_id = seed_user(email="admin-ok@example.com")
    grant_platform_admin(user_id=user_id)
    app = _probe_app(admin_db_sessionmaker)
    transport = ASGITransport(app=app)
    cookie = _cookie_for(user_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/probe/admin-only", cookies={"walleza_access": cookie})

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user_id)


async def test_non_admin_denied_403(seed_user, admin_db_sessionmaker) -> None:
    user_id = seed_user(email="non-admin@example.com")
    app = _probe_app(admin_db_sessionmaker)
    transport = ASGITransport(app=app)
    cookie = _cookie_for(user_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/probe/admin-only", cookies={"walleza_access": cookie})

    assert response.status_code == 403


async def test_unauthenticated_denied_401(admin_db_sessionmaker) -> None:
    app = _probe_app(admin_db_sessionmaker)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get("/probe/admin-only")

    assert response.status_code == 401


async def test_revoked_admin_loses_access_on_next_call(
    seed_user, grant_platform_admin, db_session, admin_db_sessionmaker
) -> None:
    import sqlalchemy as sa

    user_id = seed_user(email="revoked-admin@example.com")
    grant_platform_admin(user_id=user_id)
    app = _probe_app(admin_db_sessionmaker)
    transport = ASGITransport(app=app)
    cookie = _cookie_for(user_id)

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        first = await client.get("/probe/admin-only", cookies={"walleza_access": cookie})
        db_session.execute(
            sa.text("DELETE FROM app.platform_admin WHERE user_id = :uid"), {"uid": user_id}
        )
        db_session.commit()
        second = await client.get("/probe/admin-only", cookies={"walleza_access": cookie})

    assert first.status_code == 200
    assert second.status_code == 403
