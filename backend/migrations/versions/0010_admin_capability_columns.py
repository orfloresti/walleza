"""admin capability columns

Adds `app.app_user.deactivated_at` (design D101) and
`app.workspace.is_active` (design D106) — the two columns the
platform-admin CAPABILITY endpoints shipped in this Unit (Phase 8 Unit 3:
deactivate/reactivate user, deactivate/reactivate workspace) need
somewhere to write their flag to.

Judgment call (Unit 3 apply): design's own text places both columns
alongside their ENFORCEMENT sites — `deactivated_at` checked in the
login/refresh path and in `require_platform_admin`'s own re-resolution
(D101), `is_active` checked inside `require_membership` for the read-only
lockout (D106) — and tasks.md nominally schedules that enforcement work
for Unit 4 (`workspace.is_active BOOLEAN NOT NULL DEFAULT true` migration,
task 4.1). But Unit 3's own task 3.4/3.5 ("deactivate/reactivate user",
"sets is_active") cannot exist without the column already present, and
Unit 4's task 4.1 would otherwise just re-add a column Unit 3 already
needed. Splitting the column addition into its own Unit-4-only migration
would force Unit 3's admin endpoints to write to a column that doesn't
exist yet. Column addition is therefore pulled forward to the Unit that
first needs somewhere to write the flag (this Unit); the actual
LOCKOUT/LOGIN-BLOCK enforcement behavior stays exactly where design and
tasks.md place it — Unit 4, `require_membership` and the auth/session
path — unchanged by this migration. Both columns are additive, nullable
or safely-defaulted, and inert until Unit 4 wires their enforcement.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("deactivated_at", TIMESTAMP(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "workspace",
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("workspace", "is_active", schema=SCHEMA)
    op.drop_column("app_user", "deactivated_at", schema=SCHEMA)
