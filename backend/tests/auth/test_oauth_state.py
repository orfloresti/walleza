"""RED -> GREEN: absent/mismatched OAuth `state` is rejected (task 3.1).

Design D7: `state` + `code_verifier` travel in a 10-minute signed httpOnly
cookie (stateless, no server-side store — required for Lambda). The
callback endpoint MUST reject the exchange whenever the cookie is
missing, the query `state` is missing, the two do not match, or the
cookie has expired.
"""

import time

import pytest

from app.auth.google import (
    OAuthStateError,
    create_state_cookie_value,
    verify_callback_state,
)


def test_absent_state_cookie_is_rejected() -> None:
    with pytest.raises(OAuthStateError):
        verify_callback_state(cookie_value=None, query_state="some-state")


def test_absent_query_state_is_rejected() -> None:
    cookie_value = create_state_cookie_value(
        state="abc123", code_verifier="verifier-xyz", nonce="nonce-xyz"
    )

    with pytest.raises(OAuthStateError):
        verify_callback_state(cookie_value=cookie_value, query_state=None)


def test_mismatched_state_is_rejected() -> None:
    cookie_value = create_state_cookie_value(
        state="abc123", code_verifier="verifier-xyz", nonce="nonce-xyz"
    )

    with pytest.raises(OAuthStateError):
        verify_callback_state(cookie_value=cookie_value, query_state="a-different-state")


def test_expired_state_cookie_is_rejected() -> None:
    an_hour_ago = int(time.time()) - 3600
    cookie_value = create_state_cookie_value(
        state="abc123", code_verifier="verifier-xyz", nonce="nonce-xyz", now=an_hour_ago
    )

    with pytest.raises(OAuthStateError):
        verify_callback_state(cookie_value=cookie_value, query_state="abc123")


def test_matching_state_is_accepted() -> None:
    cookie_value = create_state_cookie_value(
        state="abc123", code_verifier="verifier-xyz", nonce="nonce-xyz"
    )

    payload = verify_callback_state(cookie_value=cookie_value, query_state="abc123")

    assert payload.state == "abc123"
    assert payload.code_verifier == "verifier-xyz"
    assert payload.nonce == "nonce-xyz"
