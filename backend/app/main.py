"""FastAPI application factory.

`create_app()` builds and returns a fresh app instance so both tests
(via httpx's `ASGITransport`) and the Lambda handler get an identically
configured app without duplicating route/middleware wiring in two
places.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.accounts.router import router as accounts_router
from app.auth.router import router as auth_router
from app.categories.router import router as categories_router
from app.config import get_settings
from app.transactions.router import router as transactions_router
from app.workspace.router import bootstrap_router as workspace_bootstrap_router
from app.workspace.router import router as workspace_router

ORIGIN_TOKEN_HEADER = b"x-origin-token"

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class OriginTokenMiddleware:
    """Reject any request not carrying the Cloudflare Worker's
    `X-Origin-Token` header (design D9). The Lambda Function URL is
    `AuthType: NONE` and reachable directly on the public internet; this
    header is the only thing standing between it and the open internet
    once the Worker is deployed.

    Enforcement is skipped while `worker_origin_token` is unset (empty
    string) — the local-dev default, matching every other real secret
    (`google_client_id`, etc.) in `app/config.py`. There is no real
    Worker deployed in this sandbox to issue the header, so requiring it
    unconditionally would make the app unusable locally.

    Implemented as a raw ASGI middleware (not Starlette's
    `BaseHTTPMiddleware`/`@app.middleware("http")`) — that helper buffers
    the response through a background task and is documented to swallow
    exceptions or produce an incomplete ASGI response cycle in some
    request/response shapes, which broke `POST` endpoints in this app
    during implementation.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        expected_token = get_settings().worker_origin_token
        if expected_token:
            headers = dict(scope.get("headers") or [])
            provided_token = headers.get(ORIGIN_TOKEN_HEADER)
            if provided_token is None or provided_token.decode("latin-1") != expected_token:
                response = JSONResponse({"detail": "invalid origin"}, status_code=401)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="walleza", version=settings.app_version)
    app.add_middleware(OriginTokenMiddleware)
    app.include_router(auth_router)
    app.include_router(workspace_bootstrap_router)
    app.include_router(workspace_router)
    app.include_router(accounts_router)
    app.include_router(categories_router)
    app.include_router(transactions_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness/readiness probe — see design interface contract."""
        return {
            "status": "ok",
            "version": settings.app_version,
            "commit": settings.commit_sha,
        }

    return app


app = create_app()
