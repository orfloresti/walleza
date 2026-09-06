"""Unit test for `GET /api/health`, using httpx's `ASGITransport` per the
design's testing strategy (no live server process, no `TestClient`)."""

from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_health_endpoint_returns_ok_with_version_and_commit() -> None:
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "commit" in body
