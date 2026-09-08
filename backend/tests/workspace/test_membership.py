"""RED -> GREEN:

- `require_membership` rejects a caller with no `workspace_member` row at
  all with 403 (not 404 — design D18) and zero rows of data (spec RED #1,
  tasks.md task 3.1).
- A removed member's still-valid, un-reissued access JWT is rejected on
  the very next request — the whole point of resolving membership
  per-request instead of trusting a JWT claim (design D14's stated D8
  gap closure; spec RED #4, tasks.md task 3.2).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from app.security import issue_access_token


async def test_non_member_request_to_workspace_scoped_endpoint_is_rejected_with_403(
    seed_user, app_factory
) -> None:
    user_id = seed_user(email="lonely@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    # `GET /api/workspace/invites` is behind `require_membership`; this
    # user has NEVER called the bootstrap `GET /api/workspace`, so they
    # hold no `workspace_member` row at all.
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        response = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": cookie}
        )

    assert response.status_code == 403
    # Zero rows: a rejection must never leak an invite list body.
    assert "expires_at" not in response.text


async def test_removed_members_still_valid_access_jwt_is_rejected_on_next_request(
    seed_user, app_factory, workspace_db_sessionmaker
) -> None:
    user_id = seed_user(email="removed@example.com")
    app = app_factory()
    transport = ASGITransport(app=app)
    cookie = issue_access_token(user_id=str(user_id), session_id=str(uuid.uuid4()))

    async with AsyncClient(transport=transport, base_url="https://test") as client:
        # Establish membership via the bootstrap get-or-create route.
        first = await client.get("/api/workspace", cookies={"walleza_access": cookie})
        assert first.status_code == 200

        # Remove the membership row directly (out-of-band), simulating
        # another member having already called
        # `DELETE /api/workspace/members/{user_id}` — this test's target
        # is `require_membership`'s PER-REQUEST re-check, not the removal
        # endpoint's own correctness (covered separately).
        with workspace_db_sessionmaker() as session:
            session.execute(
                sa.text("DELETE FROM app.workspace_member WHERE user_id = :uid"),
                {"uid": user_id},
            )
            session.commit()

        # The SAME still-valid JWT, never re-issued, must now be rejected.
        second = await client.get(
            "/api/workspace/invites", cookies={"walleza_access": cookie}
        )

    assert second.status_code == 403
