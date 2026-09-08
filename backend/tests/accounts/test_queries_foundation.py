"""Foundation test for `app.accounts.queries.visible_accounts` (design
D15) — proves the predicate itself is correct against a real Postgres
database: a shared account and the scope-owner's own personal account are
visible; another member's personal account is not.

Full account CRUD and the complete cross-member visibility RED test suite
(spec RED #2/#3/#12) are PR3's scope (tasks.md Phase 5, `test_visibility.py`
and friends). This test exists only to prove PR3's foundation
(`visible_accounts`, `WorkspaceScope`) is sound BEFORE PR3 builds account
CRUD on top of it — not to duplicate PR3's own RED suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope


def test_visible_accounts_includes_shared_and_own_personal_excludes_others_personal(
    accounts_db_sessionmaker,
) -> None:
    with accounts_db_sessionmaker() as session:
        workspace_id = uuid.uuid4()
        owner_a = uuid.uuid4()
        owner_b = uuid.uuid4()
        now = datetime.now(UTC)

        session.execute(
            sa.text(
                "INSERT INTO app.workspace (id, name, created_at, updated_at) "
                "VALUES (:id, 'WS', :now, :now)"
            ),
            {"id": workspace_id, "now": now},
        )
        for uid, email in ((owner_a, "a@example.com"), (owner_b, "b@example.com")):
            session.execute(
                sa.text(
                    "INSERT INTO app.app_user (id, google_sub, email, created_at, updated_at) "
                    "VALUES (:id, :sub, :email, now(), now())"
                ),
                {"id": uid, "sub": f"sub-{uid}", "email": email},
            )
        session.execute(
            sa.text(
                "INSERT INTO app.account (id, workspace_id, owner_user_id, name, currency, is_personal) "
                "VALUES "
                "(gen_random_uuid(), :wsid, NULL, 'Shared', 'USD', false), "
                "(gen_random_uuid(), :wsid, :a, 'A Personal', 'USD', true), "
                "(gen_random_uuid(), :wsid, :b, 'B Personal', 'USD', true)"
            ),
            {"wsid": workspace_id, "a": owner_a, "b": owner_b},
        )
        session.commit()

        scope_a = WorkspaceScope(user_id=owner_a, workspace_id=workspace_id)
        names_visible_to_a = {row.name for row in session.execute(visible_accounts(scope_a)).scalars()}

        scope_b = WorkspaceScope(user_id=owner_b, workspace_id=workspace_id)
        names_visible_to_b = {row.name for row in session.execute(visible_accounts(scope_b)).scalars()}

    assert names_visible_to_a == {"Shared", "A Personal"}
    assert names_visible_to_b == {"Shared", "B Personal"}
