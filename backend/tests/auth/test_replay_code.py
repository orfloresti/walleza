"""RED -> GREEN: a replayed OAuth authorization code is rejected (task 3.2).

The guard must reject the SECOND use of a given `code` BEFORE a second
network call is made to Google's token endpoint — replay must not cost a
Google round trip, and must not depend solely on Google's own
`invalid_grant` response.
"""

import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.google import ReplayedAuthorizationCodeError, complete_login
from app.config import get_settings


@pytest.fixture
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_id_token(private_key, *, nonce: str = "expected-nonce") -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.google_issuer,
        "aud": settings.google_client_id,
        "sub": "google-sub-replay",
        "email": "replay@example.com",
        "nonce": nonce,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "test-kid"})


def test_replayed_authorization_code_is_rejected_before_hitting_google(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair
) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public_key)),
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "access_token": "google-access-token",
                "id_token": _make_id_token(private_key),
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    transport = httpx.MockTransport(handler)

    identity = complete_login(
        code="one-time-code", code_verifier="verifier", nonce="expected-nonce", transport=transport
    )
    assert identity.google_sub == "google-sub-replay"
    assert call_count == 1

    with pytest.raises(ReplayedAuthorizationCodeError):
        complete_login(
            code="one-time-code", code_verifier="verifier", nonce="expected-nonce", transport=transport
        )

    # The replay must be rejected by the guard itself, not by a second
    # (wasted) call to Google's token endpoint.
    assert call_count == 1

    get_settings.cache_clear()


def test_different_codes_are_independent(monkeypatch: pytest.MonkeyPatch, rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "test-client-id")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.security._get_google_jwks_client",
        lambda: SimpleNamespace(get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=public_key)),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "google-access-token",
                "id_token": _make_id_token(private_key),
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )

    transport = httpx.MockTransport(handler)

    complete_login(code="code-a", code_verifier="verifier", nonce="expected-nonce", transport=transport)
    # A different code must not be rejected as a replay of "code-a".
    complete_login(code="code-b", code_verifier="verifier", nonce="expected-nonce", transport=transport)

    get_settings.cache_clear()
