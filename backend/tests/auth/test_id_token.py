"""RED -> GREEN: Google ID-token claim rejection, wired through the OAuth
login flow (task 3.3-3.5).

`app.security.verify_google_id_token` already has its own low-level unit
tests (`tests/test_security.py`) exercising the raw crypto primitive.
These tests instead exercise the WIRING in `app.auth.google.complete_login`
— the code path a real callback actually calls — so a bad ID token
returned by Google's token endpoint is proven to fail the whole login,
not just the isolated verification function.
"""

import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.google import complete_login
from app.config import get_settings
from app.security import TokenError


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_id_token(private_key, **claim_overrides) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.google_issuer,
        "aud": settings.google_client_id,
        "sub": "google-sub-abc",
        "email": "user@example.com",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claim_overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


def _transport_returning(id_token: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "google-access-token",
                "id_token": id_token,
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    return httpx.MockTransport(handler)


def _patch_jwks(monkeypatch: pytest.MonkeyPatch, public_key) -> None:
    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public_key)),
    )


def test_wrong_aud(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "expected-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    id_token = _make_id_token(private_key, aud="some-other-client-id")

    with pytest.raises(TokenError):
        complete_login(
            code="auth-code-wrong-aud",
            code_verifier="verifier",
            nonce="expected-nonce",
            transport=_transport_returning(id_token),
        )

    get_settings.cache_clear()


def test_wrong_iss(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    id_token = _make_id_token(private_key, iss="https://not-google.example.com")

    with pytest.raises(TokenError):
        complete_login(
            code="auth-code-wrong-iss",
            code_verifier="verifier",
            nonce="expected-nonce",
            transport=_transport_returning(id_token),
        )

    get_settings.cache_clear()


def test_expired(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    an_hour_ago = int(time.time()) - 3600
    id_token = _make_id_token(private_key, iat=an_hour_ago - 3600, exp=an_hour_ago)

    with pytest.raises(TokenError):
        complete_login(
            code="auth-code-expired",
            code_verifier="verifier",
            nonce="expected-nonce",
            transport=_transport_returning(id_token),
        )

    get_settings.cache_clear()


# --- nonce (design D7: verify iss/aud/exp/nonce) ----------------------------
#
# `complete_login` is the wiring a real callback actually calls (same
# rationale as the aud/iss/exp tests above): the `nonce` stored in the
# signed state cookie by `app.auth.google.create_state_cookie_value` must
# be threaded through to `app.security.verify_google_id_token`, and a
# missing or mismatched `nonce` claim on the ID token Google returns must
# reject the login exactly like a bad `aud`/`iss`/`exp` does.


def test_missing_nonce_claim_is_rejected(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    # No `nonce` claim at all on the ID token, but the callback expects one.
    id_token = _make_id_token(private_key)

    with pytest.raises(TokenError):
        complete_login(
            code="auth-code-missing-nonce",
            code_verifier="verifier",
            nonce="expected-nonce",
            transport=_transport_returning(id_token),
        )

    get_settings.cache_clear()


def test_mismatched_nonce_is_rejected(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    id_token = _make_id_token(private_key, nonce="a-different-nonce")

    with pytest.raises(TokenError):
        complete_login(
            code="auth-code-mismatched-nonce",
            code_verifier="verifier",
            nonce="expected-nonce",
            transport=_transport_returning(id_token),
        )

    get_settings.cache_clear()


def test_matching_nonce_is_accepted(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    """A legitimate ID token whose `nonce` claim matches the one the
    caller supplies (i.e. the value round-tripped through the signed
    state cookie) passes through the full login wiring successfully."""
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()
    _patch_jwks(monkeypatch, public_key)

    id_token = _make_id_token(private_key, nonce="expected-nonce")

    identity = complete_login(
        code="auth-code-matching-nonce",
        code_verifier="verifier",
        nonce="expected-nonce",
        transport=_transport_returning(id_token),
    )

    assert identity.google_sub == "google-sub-abc"
    assert identity.email == "user@example.com"

    get_settings.cache_clear()
