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

from sqlalchemy import Column, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
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


class Base(DeclarativeBase):
    """Shared declarative registry for the Phase 1+ product-domain ORM models.

    Design ref: D11. `app/auth/session.py` predates this class and keeps its
    own hand-written SQLAlchemy Core `Table` objects on a separate, private
    `MetaData(schema="app")` — it is NOT retrofitted onto this `Base`
    (confirmed decision 8 / D11: a scoped deviation, not a migration of
    existing code). Every later feature module (`app/workspace/models.py`,
    `app/accounts/models.py`, ...) declares its ORM models against THIS one
    `Base` instead of its own per-module registry, so a cross-module foreign
    key (e.g. `app.account.workspace_id -> app.workspace.id`) can be
    expressed as a plain string without importing the other feature
    module — avoiding import cycles between sibling feature packages.

    `migrations/env.py`'s `target_metadata` stays `None` on purpose: this
    `Base.metadata` is never wired into Alembic autogenerate. Every revision,
    including `0002_workspace_accounts.py`, remains hand-written DDL so the
    reviewed migration surface stays byte-for-byte in the same shape as
    `0001_baseline.py`.
    """

    metadata = MetaData(schema="app")


# Minimal FK-resolution stub for `app.app_user`, NOT a mapped model.
#
# `app_user` is created by `0001_baseline.py` and owned by
# `app/auth/session.py`'s own hand-written Core `Table` on ITS OWN separate
# `MetaData` instance (confirmed decision 8 / D11 — not retrofitted here).
# But several Phase 1+ models declared against `Base` above (e.g.
# `Workspace.created_by_user_id`, `Account.owner_user_id`) hold a real
# `ForeignKey("app.app_user.id", ...)`. SQLAlchemy's ORM unit-of-work needs
# to resolve that `ForeignKey` to an actual `Table` object registered on
# THIS SAME `Base.metadata` in order to topologically sort tables during
# `Session.flush()` — a plain string reference is not enough at that point,
# even though no DDL is ever emitted from `Base.metadata` (`target_metadata`
# stays `None`; see module docstring above). Two independent `Table` objects
# named "app_user" safely coexist because they live in two separate
# `MetaData` instances; only the ONE physical database table `0001` created
# is ever touched, and this stub is deliberately just the `id` column,
# never queried or mapped to a class directly.
_app_user_ref = Table(
    "app_user",
    Base.metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
)
