"""JWT and Google ID-token verification primitives.

This module holds only reusable crypto/verification building blocks:

- issuing and verifying our own short-lived access JWT (design D8)
- verifying a Google-issued ID token against Google's published JWKS
  (design D7)

Wiring these into actual OAuth endpoints (login/callback/refresh/logout,
cookie handling, PKCE/state, session persistence) is Phase 3/4 (PR3) —
out of scope here.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import get_settings


class TokenError(Exception):
    """Raised for any structural, signature, claim, or expiry failure.

    Callers should treat every `TokenError` uniformly as "not
    authenticated" — the spec requires missing, expired, and invalid
    tokens to all be rejected the same way.
    """


@dataclass(frozen=True)
class AccessTokenClaims:
    """Decoded claims from one of our own access JWTs."""

    sub: str
    sid: str
    jti: str
    iat: int
    exp: int


def issue_access_token(
    user_id: str,
    session_id: str,
    *,
    now: int | None = None,
) -> str:
    """Issue a short-lived (15-minute default) access JWT.

    The `kid` header is set from day one (design D8) so a future
    multi-key rotation can select the correct verification key per
    token without a breaking change to tokens already issued under the
    current key.

    `now` is accepted as an override (rather than always reading the
    real clock) so tests can construct an already-expired token
    deterministically without sleeping.
    """
    settings = get_settings()
    issued_at = now if now is not None else int(time.time())
    expires_at = issued_at + settings.jwt_access_ttl_seconds

    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": user_id,
        "sid": session_id,
        "jti": str(uuid.uuid4()),
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm="HS256",
        headers={"kid": settings.jwt_kid},
    )


def verify_access_token(token: str) -> AccessTokenClaims:
    """Verify and decode one of our own access JWTs.

    Raises `TokenError` on bad signature, wrong issuer/audience,
    expiry, or missing claims.
    """
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    try:
        return AccessTokenClaims(
            sub=payload["sub"],
            sid=payload["sid"],
            jti=payload["jti"],
            iat=payload["iat"],
            exp=payload["exp"],
        )
    except KeyError as exc:
        raise TokenError(f"missing claim: {exc}") from exc


_google_jwks_client: PyJWKClient | None = None


def _get_google_jwks_client() -> PyJWKClient:
    """Return a lazily-built, process-cached JWKS client for Google's keys.

    Lazy so importing this module never performs a network call; the
    client fetches (and internally caches) Google's JWKS only on first
    actual verification. Tests replace this function via `monkeypatch`
    to avoid any real network access.
    """
    global _google_jwks_client
    if _google_jwks_client is None:
        settings = get_settings()
        _google_jwks_client = PyJWKClient(settings.google_jwks_url)
    return _google_jwks_client


def verify_google_id_token(id_token: str, *, nonce: str | None = None) -> dict[str, Any]:
    """Verify a Google-issued ID token against Google's JWKS.

    Checks signature, `iss`, `aud` (our Google OAuth client ID), and
    `exp` (design D7). When `nonce` is provided, it is compared against
    the token's `nonce` claim. Returns the decoded claims on success;
    raises `TokenError` otherwise.
    """
    settings = get_settings()
    try:
        signing_key = _get_google_jwks_client().get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=settings.google_issuer,
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if nonce is not None and claims.get("nonce") != nonce:
        raise TokenError("nonce mismatch")

    return claims
