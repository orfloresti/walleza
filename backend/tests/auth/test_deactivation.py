"""RED -> GREEN: Phase 8 design D101 / Unit 4 task 4.4 — a deactivated
user cannot log in, and an existing (unexpired, unrevoked) refresh token
is rejected once its owner is deactivated. Reactivation restores login.

Runs against a REAL, ephemeral PostgreSQL server (see `conftest.py`
`auth_db_sessionmaker`), mirroring `test_refresh_reuse.py`'s pattern.
"""

import sqlalchemy as sa

from app.auth.session import (
    UserDeactivatedError,
    app_user_table,
    create_session,
    rotate_refresh_token,
    upsert_user_by_google_sub,
)


def _deactivate(db_session, *, user_id) -> None:
    db_session.execute(
        sa.update(app_user_table).where(app_user_table.c.id == user_id).values(deactivated_at=sa.func.now())
    )
    db_session.commit()


def _reactivate(db_session, *, user_id) -> None:
    db_session.execute(
        sa.update(app_user_table).where(app_user_table.c.id == user_id).values(deactivated_at=None)
    )
    db_session.commit()


def test_deactivated_user_cannot_log_in(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-deact-1", email="a@example.com")
    _deactivate(db_session, user_id=user_id)

    try:
        create_session(db_session, user_id=user_id)
        raise AssertionError("expected UserDeactivatedError")
    except UserDeactivatedError:
        pass


def test_deactivated_users_existing_refresh_token_is_rejected(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-deact-2", email="b@example.com")
    issued = create_session(db_session, user_id=user_id)

    _deactivate(db_session, user_id=user_id)

    try:
        rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)
        raise AssertionError("expected UserDeactivatedError")
    except UserDeactivatedError:
        pass


def test_reactivation_restores_login(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-deact-3", email="c@example.com")
    _deactivate(db_session, user_id=user_id)
    _reactivate(db_session, user_id=user_id)

    issued = create_session(db_session, user_id=user_id)

    assert issued.access_token
    assert issued.refresh_token
