"""SQLAlchemy engine setup.

The engine is created at MODULE SCOPE (import time), never inside a
function, a FastAPI dependency, or the app's lifespan. This is
load-bearing, not a style choice: Mangum is wired with
`lifespan="off"` (see `app/handler.py`, design D1) precisely because it
would otherwise re-run the ASGI lifespan on every single Lambda
invocation, which would rebuild the engine (and its connection pool
state) on every request instead of once per cold start. A module-scope
engine is what actually persists across warm invocations of the same
Lambda execution environment.

`create_engine()` itself never opens a network connection — SQLAlchemy
connects lazily on first checkout — so importing this module is always
safe, including with no database reachable at all (this sandbox, CI
without a live Supabase branch, etc.).

Design ref: D2 — connect through the Supavisor transaction pooler
(`:6543`), which forbids server-side prepared statements. `NullPool` is
used because Supavisor already pools connections upstream; a second,
client-side pool would fight it. `prepare_threshold=None` disables
psycopg's own statement-cache/prepare behavior, which is required for
transaction-pooling mode.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

_settings = get_settings()

_is_psycopg = _settings.database_url.startswith("postgresql+psycopg://")

engine: Engine = create_engine(
    _settings.database_url,
    poolclass=NullPool,
    connect_args={"prepare_threshold": None} if _is_psycopg else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> "Session":
    """FastAPI dependency that yields one session per request.

    A generator dependency: FastAPI enters it before the request handler
    and resumes it after (the `finally` block) to close the session,
    regardless of whether the request succeeded.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
