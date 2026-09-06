"""RED -> GREEN: refresh-token reuse after rotation revokes the whole
session family (task 3.6, design D8).

Runs against a REAL, ephemeral PostgreSQL server (see `conftest.py`
`auth_db_sessionmaker`) — reuse detection is security-critical and must
be proven against real FK constraints and real transactions, following
the same real-Postgres pattern established in
`backend/tests/migrations/test_baseline.py`.
"""

import pytest

from app.auth.session import (
    RefreshTokenError,
    RefreshTokenReuseError,
    create_session,
    rotate_refresh_token,
    upsert_user_by_google_sub,
)


def test_refresh_rotation_issues_a_new_pair_and_keeps_the_family_stable(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-rotate-1", email="a@example.com")
    issued = create_session(db_session, user_id=user_id)

    rotated = rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)

    assert rotated.refresh_token != issued.refresh_token
    assert rotated.access_token != issued.access_token
    assert rotated.family_id == issued.family_id


def test_reusing_a_rotated_refresh_token_is_rejected(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-rotate-2", email="b@example.com")
    issued = create_session(db_session, user_id=user_id)

    rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)

    with pytest.raises(RefreshTokenReuseError):
        rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)


def test_refresh_reuse_revokes_the_entire_family(db_session) -> None:
    user_id = upsert_user_by_google_sub(db_session, google_sub="sub-rotate-3", email="c@example.com")
    issued = create_session(db_session, user_id=user_id)
    rotated_once = rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)

    with pytest.raises(RefreshTokenReuseError):
        rotate_refresh_token(db_session, presented_refresh_token=issued.refresh_token)

    # The legitimately-rotated successor token is ALSO dead now: reuse
    # detection revokes the whole family, not just the replayed token.
    with pytest.raises(RefreshTokenError):
        rotate_refresh_token(db_session, presented_refresh_token=rotated_once.refresh_token)


def test_unknown_refresh_token_is_rejected(db_session) -> None:
    with pytest.raises(RefreshTokenError):
        rotate_refresh_token(db_session, presented_refresh_token="not-a-real-token")


def test_repeat_login_reuses_existing_user_id(db_session) -> None:
    first_id = upsert_user_by_google_sub(db_session, google_sub="sub-repeat", email="old@example.com")
    second_id = upsert_user_by_google_sub(db_session, google_sub="sub-repeat", email="new@example.com")

    assert first_id == second_id
