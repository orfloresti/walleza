"""baseline: auth-only tables

Creates schema `app` and exactly the two auth-support tables required by
the `authentication` capability (spec: "Migration Framework with Auth-Only
Baseline"; design D3): the minimal user identity record (`app_user`) and
its session/refresh-token record (`auth_session`). This revision MUST NOT
define any other product/domain table (accounts, transactions, categories,
budgets, credit cards, debts, etc.) — those land in later phases.

Column shapes match the design's Interfaces/Contracts section exactly:

    app.app_user(id uuid pk, google_sub text unique not null, email text
                 not null, created_at timestamptz, updated_at timestamptz)
    app.auth_session(id uuid pk, user_id fk, refresh_hash text,
                      family_id uuid, expires_at timestamptz,
                      revoked_at timestamptz null)

`created_at`/`updated_at`/`refresh_hash`/`family_id`/`expires_at`/`user_id`
are made NOT NULL with sensible defaults where the design's contract did
not spell out nullability explicitly (only `google_sub`, `email`, and the
nullable `revoked_at` are called out by name) — a session or user row is
never meaningfully created without these values populated.

Revision ID: 0001
Revises:
Create Date: 2026-09-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("google_sub", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "auth_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.app_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("auth_session", schema=SCHEMA)
    op.drop_table("app_user", schema=SCHEMA)
    # Do NOT drop the `app` schema itself here: Alembic's own bookkeeping
    # table (`alembic_version`) also lives in `app` (see `migrations/env.py`
    # `VERSION_TABLE_SCHEMA`), and it must still exist immediately after
    # this downgrade() runs so Alembic can record the new (empty) version
    # state in the same transaction.
