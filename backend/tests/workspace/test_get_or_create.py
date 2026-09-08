"""RED -> GREEN: concurrent double `GET /api/workspace` for a brand-new
user yields exactly one workspace and one `workspace_member` row.

`uq_workspace_member_user_id` (PR1's migration) is the real backstop; this
test proves the actual race resolves cleanly end to end — two real
threads, each with its OWN `Session` bound to the SAME real ephemeral
Postgres, racing `get_or_create_workspace` for the SAME user via a
`threading.Barrier` to maximize genuine contention — not merely that the
constraint exists in isolation (spec RED #11, tasks.md task 3.3).
"""

from __future__ import annotations

import threading
import uuid

import sqlalchemy as sa

from app.workspace.service import get_or_create_workspace


def test_concurrent_get_or_create_yields_exactly_one_workspace(
    seed_user, workspace_db_sessionmaker
) -> None:
    user_id = seed_user(email="race@example.com")

    barrier = threading.Barrier(2)
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        session = workspace_db_sessionmaker()
        try:
            barrier.wait(timeout=5)
            workspace = get_or_create_workspace(session, user_id=user_id)
            session.commit()
            with lock:
                results.append(workspace.id)
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            with lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, (
        "get_or_create_workspace must resolve the race internally "
        f"(catch IntegrityError and re-read), got: {errors!r}"
    )
    assert len(results) == 2
    assert results[0] == results[1], "both concurrent calls must resolve to the SAME workspace"

    with workspace_db_sessionmaker() as session:
        workspace_count = session.execute(
            sa.text("SELECT count(*) FROM app.workspace WHERE created_by_user_id = :uid"),
            {"uid": user_id},
        ).scalar_one()
        member_count = session.execute(
            sa.text("SELECT count(*) FROM app.workspace_member WHERE user_id = :uid"),
            {"uid": user_id},
        ).scalar_one()

    assert workspace_count == 1, "the losing thread's half-built workspace must not survive"
    assert member_count == 1
