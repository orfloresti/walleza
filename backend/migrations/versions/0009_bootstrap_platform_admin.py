"""bootstrap platform admin

Data-only migration (no DDL) that seeds the first platform admin, per the
`platform-admin` domain's "Bootstrap Idempotency" requirement and design
D107. A SEPARATE revision from `0008_platform_admin.py` (which only adds
the table) so this data seed can be re-run without re-running any DDL —
Alembic will not re-run an already-applied revision regardless, but
keeping the seed in its own revision keeps `0008` a pure, trivially
reversible schema change.

`upgrade()` delegates to `app.admin.bootstrap.run_bootstrap`, the exact
same function the `python -m app.admin.bootstrap` CLI entrypoint calls
(design D107) — one idempotent implementation, two callers. Re-run path
for the realistic "deploy before first login" ordering: run the CLI
entrypoint directly after the target user's first Google sign-in, rather
than `alembic downgrade/upgrade` (unnecessarily destructive-adjacent for
a production database, per design's own rejection of that alternative).

`downgrade()` deletes only the row this bootstrap itself inserted
(`note = 'bootstrap via INITIAL_PLATFORM_ADMIN_EMAIL'`) — never a row a
later grant/revoke capability (Unit 3) may have written.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.admin.bootstrap import run_bootstrap

    run_bootstrap(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM app.platform_admin "
            "WHERE note = 'bootstrap via INITIAL_PLATFORM_ADMIN_EMAIL'"
        )
    )
