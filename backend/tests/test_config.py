"""Unit tests for `app.config` settings loading.

Every test that mutates environment variables clears the `get_settings`
cache before and after, since `get_settings()` is process-wide cached
(design note in `app/config.py`).
"""

from app.config import get_settings


def test_settings_has_safe_local_defaults() -> None:
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.environment == "local"
    assert settings.jwt_issuer == "walleza"
    assert settings.jwt_audience == "walleza-web"
    assert settings.jwt_access_ttl_seconds == 15 * 60
    assert settings.google_jwks_url == "https://www.googleapis.com/oauth2/v3/certs"


def test_settings_reads_from_walleza_prefixed_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("WALLEZA_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("WALLEZA_DATABASE_URL", "postgresql+psycopg://u:p@localhost:6543/db")
    monkeypatch.setenv("WALLEZA_GOOGLE_CLIENT_ID", "unit-test-client-id")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.jwt_secret == "unit-test-secret"
    assert settings.database_url == "postgresql+psycopg://u:p@localhost:6543/db"
    assert settings.google_client_id == "unit-test-client-id"

    get_settings.cache_clear()


def test_unprefixed_env_vars_are_ignored(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "should-not-be-picked-up")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.jwt_secret != "should-not-be-picked-up"

    get_settings.cache_clear()


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()

    assert first is second

    get_settings.cache_clear()
