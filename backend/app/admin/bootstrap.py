"""Idempotent platform-admin bootstrap logic (design D107).

The exact same four-step logic is shared by two callers:

- the data migration `migrations/versions/0009_bootstrap_platform_admin.py`
  (runs once at deploy time, on `alembic upgrade head`), and
- the `python -m app.admin.bootstrap` CLI entrypoint, the re-runnable
  operational path for the realistic "seed before first login" ordering:
  Alembic will never re-run an already-applied revision, so an operator
  who deploys before the target user has ever signed in via Google must
  re-run the bootstrap AFTER that first login — this module, not
  `alembic downgrade/upgrade`, is the intended way to do that (design
  D107's own recommendation, chosen over the destructive-adjacent
  downgrade/upgrade round trip).

`run_bootstrap` takes a plain `sqlalchemy.Connection` (not an ORM
`Session`) so it works identically whether called from `op.get_bind()`
inside a migration or from a fresh `engine.begin()` connection in the CLI
entrypoint — no ORM model dependency, no app-level session machinery
needed for a one-time bootstrap.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import sqlalchemy as sa

logger = logging.getLogger(__name__)

# Read as a raw, unprefixed environment variable (design D107's own
# pseudocode) — deliberately NOT routed through `app.config.Settings`
# (which prefixes every field with `WALLEZA_`): this is a one-time
# deploy-time bootstrap input, not ongoing runtime configuration, and
# keeping it out of `Settings` means it never needs an `env_prefix`
# special case.
ENV_VAR = "INITIAL_PLATFORM_ADMIN_EMAIL"


def run_bootstrap(conn: sa.Connection) -> str:
    """Returns a short, human-readable status string for logging by
    whichever caller invoked this (the migration's own log output, or the
    CLI entrypoint's stdout) — never raises for any of the three no-op
    cases below; only a real database error propagates."""
    email = os.environ.get(ENV_VAR)
    if not email:
        message = f"no {ENV_VAR} set, skipping platform-admin bootstrap"
        logger.info(message)
        return message

    already_seeded = conn.execute(
        sa.text("SELECT 1 FROM app.platform_admin LIMIT 1")
    ).first()
    if already_seeded is not None:
        message = "platform_admin already seeded, skipping bootstrap"
        logger.info(message)
        return message

    user_row = conn.execute(
        sa.text("SELECT id FROM app.app_user WHERE email = :email"),
        {"email": email},
    ).first()
    if user_row is None:
        message = (
            f"no app_user row for {email!r} yet; the user must sign in via "
            "Google once, then this bootstrap must be re-run "
            "(python -m app.admin.bootstrap)"
        )
        logger.warning(message)
        return message

    conn.execute(
        sa.text(
            "INSERT INTO app.platform_admin (user_id, granted_at, granted_by_user_id, note) "
            "VALUES (:user_id, :granted_at, NULL, :note)"
        ),
        {
            "user_id": user_row.id,
            "granted_at": datetime.now(UTC),
            "note": "bootstrap via INITIAL_PLATFORM_ADMIN_EMAIL",
        },
    )
    message = f"granted platform-admin to {email!r} ({user_row.id})"
    logger.info(message)
    return message


def main() -> None:
    """`python -m app.admin.bootstrap` — the re-runnable operational path.
    Deferred import of `app.db.engine` so this module can be imported
    (e.g. by the migration) without requiring a live database connection
    at import time (matches `app/db.py`'s own import-safety guarantee)."""
    logging.basicConfig(level=logging.INFO)
    from app.db import engine

    with engine.begin() as conn:
        message = run_bootstrap(conn)
    print(message)


if __name__ == "__main__":
    main()
