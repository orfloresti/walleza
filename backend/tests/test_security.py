"""Unit tests for `app.security`: access-JWT issue/verify round-trip and
Google ID-token verification.

Google verification is tested against a locally generated RSA key pair
with `app.security._get_google_jwks_client` monkeypatched to a fake
client — no network access to Google's real JWKS is made or required.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import get_settings
from app.security import (
    TokenError,
    issue_access_token,
    verify_access_token,
    verify_google_id_token,
)

# --- Access token (our own JWT) ---------------------------------------


def test_issue_and_verify_access_token_round_trip() -> None:
    token = issue_access_token(user_id="user-1", session_id="session-1")

    claims = verify_access_token(token)

    assert claims.sub == "user-1"
    assert claims.sid == "session-1"
    assert claims.exp > claims.iat


def test_access_token_header_carries_kid_for_future_rotation() -> None:
    settings = get_settings()

    token = issue_access_token(user_id="user-1", session_id="session-1")

    header = jwt.get_unverified_header(token)
    assert header["kid"] == settings.jwt_kid


def test_expired_access_token_is_rejected() -> None:
    an_hour_ago = int(time.time()) - 3600
    token = issue_access_token(user_id="user-1", session_id="session-1", now=an_hour_ago)

    with pytest.raises(TokenError):
        verify_access_token(token)


def test_tampered_access_token_is_rejected() -> None:
    token = issue_access_token(user_id="user-1", session_id="session-1")

    with pytest.raises(TokenError):
        verify_access_token(token + "tampered")


def test_access_token_with_wrong_secret_is_rejected() -> None:
    token = jwt.encode(
        {
            "iss": get_settings().jwt_issuer,
            "aud": get_settings().jwt_audience,
            "sub": "user-1",
            "sid": "session-1",
            "jti": "some-jti",
            "iat": int(time.time()),
            "exp": int(time.time()) + 900,
        },
        "a-completely-different-secret",
        algorithm="HS256",
    )

    with pytest.raises(TokenError):
        verify_access_token(token)


# --- Google ID token verification --------------------------------------


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _fake_jwks_client(public_key) -> SimpleNamespace:
    return SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key),
    )


def _make_google_id_token(private_key, **claim_overrides) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.google_issuer,
        "aud": settings.google_client_id,
        "sub": "google-sub-123",
        "email": "user@example.com",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claim_overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


def test_verify_google_id_token_accepts_valid_token(monkeypatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: _fake_jwks_client(public_key),
    )

    token = _make_google_id_token(private_key)
    claims = verify_google_id_token(token)

    assert claims["sub"] == "google-sub-123"
    assert claims["email"] == "user@example.com"

    get_settings.cache_clear()


def test_verify_google_id_token_rejects_wrong_audience(monkeypatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "expected-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: _fake_jwks_client(public_key),
    )

    token = _make_google_id_token(private_key, aud="some-other-client-id")

    with pytest.raises(TokenError):
        verify_google_id_token(token)

    get_settings.cache_clear()


def test_verify_google_id_token_rejects_wrong_issuer(monkeypatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: _fake_jwks_client(public_key),
    )

    token = _make_google_id_token(private_key, iss="https://not-google.example.com")

    with pytest.raises(TokenError):
        verify_google_id_token(token)

    get_settings.cache_clear()


def test_verify_google_id_token_rejects_expired_token(monkeypatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: _fake_jwks_client(public_key),
    )

    an_hour_ago = int(time.time()) - 3600
    token = _make_google_id_token(private_key, iat=an_hour_ago - 3600, exp=an_hour_ago)

    with pytest.raises(TokenError):
        verify_google_id_token(token)

    get_settings.cache_clear()


def test_verify_google_id_token_rejects_nonce_mismatch(monkeypatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: _fake_jwks_client(public_key),
    )

    token = _make_google_id_token(private_key, nonce="expected-nonce")

    with pytest.raises(TokenError):
        verify_google_id_token(token, nonce="a-different-nonce")

    get_settings.cache_clear()
