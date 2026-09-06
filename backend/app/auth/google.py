"""Google OAuth Authorization Code + PKCE wiring (design D7).

Holds everything specific to talking to Google: building the
authorization URL, generating/verifying the PKCE pair and the signed
`state` cookie, exchanging an authorization code for tokens, and a
one-time code-exchange guard against replay. ID-token *cryptographic*
verification itself (JWKS fetch, signature, `iss`/`aud`/`exp`) lives in
`app.security.verify_google_id_token` — this module is the caller that
wires that primitive into the OAuth flow.

FastAPI is the confidential OAuth client: the client secret and the
Google tokens never reach the browser (design D7). `state` and
`code_verifier` travel in a short-lived signed httpOnly cookie rather
than a server-side store, because Lambda has no persistent in-memory
state across invocations (design D1).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.config import get_settings
from app.security import verify_google_id_token

# --- PKCE ----------------------------------------------------------------


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def generate_pkce_pair() -> PkcePair:
    """Generate an RFC 7636 S256 PKCE verifier/challenge pair."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    """Generate a cryptographically random OpenID Connect `nonce`.

    Sent as the `nonce` authorization-request parameter, stored alongside
    `state`/`code_verifier` in the signed state cookie, and required to
    match the ID token's own `nonce` claim on callback (design D7)."""
    return secrets.token_urlsafe(32)


# --- state cookie ----------------------------------------------------------


class OAuthStateError(Exception):
    """Raised when the OAuth `state` is absent, expired, or does not match
    the value presented on the callback request."""


@dataclass(frozen=True)
class StateCookiePayload:
    state: str
    code_verifier: str
    nonce: str


def create_state_cookie_value(
    *, state: str, code_verifier: str, nonce: str, now: int | None = None
) -> str:
    """Sign `state` + `code_verifier` + `nonce` into a short-lived
    (10-min default) JWT for the `pkce_state` cookie. Stateless by
    design — no server-side store — see design D7. `nonce` rides in the
    same cookie so the callback can verify it against the ID token's own
    `nonce` claim (`app.security.verify_google_id_token`).

    `now` is accepted as an override so tests can construct an
    already-expired cookie deterministically without sleeping.
    """
    settings = get_settings()
    issued_at = now if now is not None else int(time.time())
    payload = {
        "state": state,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "iat": issued_at,
        "exp": issued_at + settings.oauth_state_ttl_seconds,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_callback_state(
    *, cookie_value: str | None, query_state: str | None
) -> StateCookiePayload:
    """Validate the callback's `state` query parameter against the signed
    `pkce_state` cookie. Rejects a missing cookie, a missing query
    `state`, a mismatch, an expired/tampered cookie, or a cookie missing
    the `nonce` claim.
    """
    if not cookie_value:
        raise OAuthStateError("missing pkce_state cookie")
    if not query_state:
        raise OAuthStateError("missing state query parameter")

    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(cookie_value, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise OAuthStateError(f"invalid or expired state cookie: {exc}") from exc

    cookie_state = payload.get("state", "")
    if not secrets.compare_digest(cookie_state, query_state):
        raise OAuthStateError("state mismatch")

    try:
        return StateCookiePayload(
            state=payload["state"],
            code_verifier=payload["code_verifier"],
            nonce=payload["nonce"],
        )
    except KeyError as exc:
        raise OAuthStateError(f"missing claim in state cookie: {exc}") from exc


# --- authorization URL -----------------------------------------------------


def build_authorization_url(*, state: str, code_challenge: str, nonce: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{settings.google_authorization_endpoint}?{urlencode(params)}"


# --- one-time code-exchange guard (task 4.2) --------------------------------


class ReplayedAuthorizationCodeError(Exception):
    """Raised when an authorization `code` is presented a second time."""


_consumed_codes: dict[str, float] = {}
_consumed_codes_lock = threading.Lock()
_CODE_GUARD_TTL_SECONDS = 600  # matches the state cookie's own lifetime


def consume_authorization_code(code: str, *, now: float | None = None) -> None:
    """Record `code` as used, raising `ReplayedAuthorizationCodeError` if
    it was already consumed. Defense in depth: Google's own token
    endpoint also rejects a reused code (`invalid_grant`), but this guard
    rejects the replay before ever spending a network round trip on it.

    In-memory and process-global, which is a real limitation on Lambda
    (a cold start starts empty). It is intentionally NOT the sole
    security boundary — Google's own one-time-code enforcement is.
    """
    effective_now = now if now is not None else time.time()
    with _consumed_codes_lock:
        expired = [c for c, ts in _consumed_codes.items() if effective_now - ts > _CODE_GUARD_TTL_SECONDS]
        for expired_code in expired:
            del _consumed_codes[expired_code]

        if code in _consumed_codes:
            raise ReplayedAuthorizationCodeError("authorization code already used")

        _consumed_codes[code] = effective_now


# --- code exchange + ID-token verification wiring ---------------------------


@dataclass(frozen=True)
class GoogleTokenResponse:
    id_token: str
    access_token: str


@dataclass(frozen=True)
class GoogleIdentity:
    google_sub: str
    email: str


# Test-only hook: production code always calls `exchange_code_for_tokens`
# with `transport=None`, which builds a real `httpx.Client`. Tests instead
# monkeypatch this module attribute to an `httpx.MockTransport` so no
# network call to Google is ever made from a test process.
_default_transport: httpx.BaseTransport | None = None


def exchange_code_for_tokens(
    *, code: str, code_verifier: str, transport: httpx.BaseTransport | None = None
) -> GoogleTokenResponse:
    settings = get_settings()
    used_transport = transport if transport is not None else _default_transport

    with httpx.Client(transport=used_transport) as client:
        response = client.post(
            settings.google_token_endpoint,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
    response.raise_for_status()
    body = response.json()
    return GoogleTokenResponse(id_token=body["id_token"], access_token=body["access_token"])


def complete_login(
    *,
    code: str,
    code_verifier: str,
    nonce: str,
    transport: httpx.BaseTransport | None = None,
) -> GoogleIdentity:
    """Full server-side half of the OAuth flow: guard against code
    replay, exchange the code for tokens, verify the ID token against
    Google's JWKS (`iss`/`aud`/`exp`/`nonce` — design D7), and return the
    verified identity. Callers persist it via `app.auth.session`.

    `nonce` is required (not optional) — it is always sourced from the
    caller's own signed state cookie (`StateCookiePayload.nonce`), so a
    caller with no nonce to check is a programming error, not a
    legitimate "skip the check" case.
    """
    consume_authorization_code(code)
    token_response = exchange_code_for_tokens(
        code=code, code_verifier=code_verifier, transport=transport
    )
    claims = verify_google_id_token(token_response.id_token, nonce=nonce)
    return GoogleIdentity(google_sub=claims["sub"], email=claims["email"])
