"""RED -> GREEN: a request missing (or presenting the wrong) Worker
origin token is rejected at the Function URL (task 3.7, design D9).

The Lambda Function URL is `AuthType: NONE` and reachable directly on the
public internet; the `X-Origin-Token` header the Cloudflare Worker
injects on every proxied `/api/*` request is the only thing standing
between that URL and the open internet, so FastAPI middleware must
verify it on every request once a real secret is configured.

When no origin token is configured at all (local dev default, `""`),
enforcement is skipped — see `app/main.py` for the rationale.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _configure_origin_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WALLEZA_WORKER_ORIGIN_TOKEN", "test-origin-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_missing_origin_token_is_rejected() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 401


async def test_wrong_origin_token_is_rejected() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health", headers={"X-Origin-Token": "wrong-secret"})

    assert response.status_code == 401


async def test_correct_origin_token_is_accepted() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/health", headers={"X-Origin-Token": "test-origin-secret"}
        )

    assert response.status_code == 200


async def test_no_configured_origin_token_skips_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    # Overrides the autouse fixture's secret back to the local-dev default
    # ("" — unset) to prove enforcement is opt-in until a real secret
    # exists, matching every other Google/JWT secret's local-dev default.
    monkeypatch.setenv("WALLEZA_WORKER_ORIGIN_TOKEN", "")
    get_settings.cache_clear()

    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
