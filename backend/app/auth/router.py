"""OAuth login/callback/refresh/logout + `/api/me` — wires
`app.auth.google` (PKCE/state, ID-token verification) and
`app.auth.session` (JWT issuance, refresh rotation/reuse detection) into
the endpoints named in the design's Interfaces/Contracts section:

    GET  /api/auth/login     302 -> Google        (sets pkce_state cookie)
    GET  /api/auth/callback  302 -> /             (sets access + refresh cookies)
    POST /api/auth/refresh   204                  (rotates both cookies)
    POST /api/auth/logout    204                  (revokes family, clears cookies)
    GET  /api/me             200 {id,email} | 401
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Cookie, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import google
from app.auth import session as auth_session
from app.config import get_settings
from app.db import get_db
from app.security import TokenError, verify_access_token

router = APIRouter(tags=["auth"])

PKCE_STATE_COOKIE = "pkce_state"
ACCESS_COOKIE = "walleza_access"
REFRESH_COOKIE = "walleza_refresh"
PKCE_STATE_COOKIE_PATH = "/api/auth"
REFRESH_COOKIE_PATH = "/api/auth/refresh"

# Cookies are marked Secure — this app is only ever served same-origin
# through the Cloudflare Worker over HTTPS (design D9); there is no HTTP
# deployment target.
_COOKIE_KWARGS = {"httponly": True, "secure": True, "samesite": "lax"}


def _set_session_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.jwt_access_ttl_seconds,
        path="/",
        **_COOKIE_KWARGS,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.refresh_ttl_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        **_COOKIE_KWARGS,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/api/auth/login")
def login() -> RedirectResponse:
    """Start the OAuth flow: mint a fresh PKCE pair + `state` + `nonce`,
    stash all three in a signed 10-minute cookie (design D7), and
    redirect to Google."""
    settings = get_settings()
    pkce = google.generate_pkce_pair()
    state = google.generate_state()
    nonce = google.generate_nonce()

    response = RedirectResponse(
        url=google.build_authorization_url(
            state=state, code_challenge=pkce.challenge, nonce=nonce
        ),
        status_code=302,
    )
    response.set_cookie(
        PKCE_STATE_COOKIE,
        google.create_state_cookie_value(
            state=state, code_verifier=pkce.verifier, nonce=nonce
        ),
        max_age=settings.oauth_state_ttl_seconds,
        path=PKCE_STATE_COOKIE_PATH,
        **_COOKIE_KWARGS,
    )
    return response


@router.get("/api/auth/callback")
def callback(
    code: str,
    state: str,
    pkce_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Response:
    """Complete the OAuth flow: verify `state`, exchange the code,
    verify the ID token, upsert the user by `google_sub`, and issue our
    own access + refresh cookies (design D7/D8)."""
    try:
        payload = google.verify_callback_state(cookie_value=pkce_state, query_state=state)
        identity = google.complete_login(
            code=code, code_verifier=payload.code_verifier, nonce=payload.nonce
        )
    except (
        google.OAuthStateError,
        google.ReplayedAuthorizationCodeError,
        TokenError,
        httpx.HTTPError,
    ):
        error_response = Response(status_code=401)
        error_response.delete_cookie(PKCE_STATE_COOKIE, path=PKCE_STATE_COOKIE_PATH)
        return error_response

    user_id = auth_session.upsert_user_by_google_sub(
        db, google_sub=identity.google_sub, email=identity.email
    )
    issued = auth_session.create_session(db, user_id=user_id)
    db.commit()

    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(PKCE_STATE_COOKIE, path=PKCE_STATE_COOKIE_PATH)
    _set_session_cookies(response, access_token=issued.access_token, refresh_token=issued.refresh_token)
    return response


@router.post("/api/auth/refresh", status_code=204)
def refresh(
    response: Response,
    walleza_refresh: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Response:
    if not walleza_refresh:
        _clear_session_cookies(response)
        response.status_code = 401
        return response

    try:
        issued = auth_session.rotate_refresh_token(db, presented_refresh_token=walleza_refresh)
    except auth_session.RefreshTokenError:
        # A reuse-detected rotation already revoked the family in the DB
        # (`rotate_refresh_token`'s side effect); persist that before
        # responding regardless of which `RefreshTokenError` was raised.
        db.commit()
        _clear_session_cookies(response)
        response.status_code = 401
        return response

    db.commit()
    _set_session_cookies(response, access_token=issued.access_token, refresh_token=issued.refresh_token)
    # Returning the injected `Response` object directly bypasses the
    # `status_code=204` route default (that default only applies when a
    # plain value is returned and FastAPI builds the response itself),
    # so the success status must be set explicitly here.
    response.status_code = 204
    return response


@router.post("/api/auth/logout", status_code=204)
def logout(
    response: Response,
    walleza_refresh: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Response:
    if walleza_refresh:
        auth_session.logout(db, presented_refresh_token=walleza_refresh)
        db.commit()
    _clear_session_cookies(response)
    response.status_code = 204
    return response


@router.get("/api/me")
def me(
    response: Response,
    walleza_access: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not walleza_access:
        response.status_code = 401
        return {"detail": "not authenticated"}

    try:
        claims = verify_access_token(walleza_access)
    except TokenError:
        response.status_code = 401
        return {"detail": "not authenticated"}

    user = auth_session.get_user_by_id(db, user_id=claims.sub)
    if user is None:
        response.status_code = 401
        return {"detail": "not authenticated"}

    return {"id": user["id"], "email": user["email"]}
