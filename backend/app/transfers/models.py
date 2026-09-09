"""ORM model for the `transfer-management` capability (design D36-D38).

Column shape matches the design's Interfaces/Contracts section exactly:

    app.transfer(id uuid pk,
        workspace_id     uuid nn fk app.workspace.id on delete cascade,
        from_account_id  uuid nn fk app.account.id   on delete NO ACTION,   -- D36
        to_account_id    uuid nn fk app.account.id   on delete NO ACTION,   -- D36
        from_amount numeric(18,2) nn, to_amount numeric(18,2) nn,           -- D37
        occurred_on date nn, notes text null,
        created_by_user_id uuid null fk app.app_user.id on delete set null,
        created_at timestamptz nn default now(), updated_at timestamptz nn default now(),
        CONSTRAINT ck_transfer_from_amount_positive  CHECK (from_amount > 0),
        CONSTRAINT ck_transfer_to_amount_positive    CHECK (to_amount > 0),
        CONSTRAINT ck_transfer_distinct_accounts     CHECK (from_account_id <> to_account_id))

Design D36: `ON DELETE NO ACTION` on BOTH account FKs — deliberately not
Phase 2's `CASCADE` and specifically `NO ACTION` rather than `RESTRICT`.
Verified against live code, not inherited: `app/accounts/router.py`
registers no DELETE route at all (Phase 1 D6 collapsed the account
lifecycle into the `archived` flag), so Phase 2's CASCADE on
`transaction.account_id` is unreachable dead code, not a precedent worth
copying. A transfer is money history on TWO accounts, so a CASCADE from
either side would silently delete a row that is still the OTHER, live
account's history.

`NO ACTION` over `RESTRICT` is load-bearing: `transfer.workspace_id` and
`account.workspace_id` are both `CASCADE` from `app.workspace`, and
Postgres fires a deleted parent's referential-action triggers across
referencing tables in UNSPECIFIED order. `RESTRICT` is checked
immediately — a workspace delete that happens to cascade `account`
before `transfer` would error out. `NO ACTION` is checked at
end-of-statement — the workspace→transfer cascade has already removed
the rows by the time the check runs. Both give an identical blocking
guarantee for a direct account delete, but only `NO ACTION` avoids the
ordering trap on workspace teardown. Proved empirically (not just
asserted) in `backend/tests/migrations/test_0004.py` (design RED #16).

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0004_transfers.py` migration (design D11's
precedent, mirroring `app/accounts/models.py`/`app/transactions/models.py`)
— this class exists so application code has a typed model to query
against, not so Alembic can autogenerate from it.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Transfer(Base):
    __tablename__ = "transfer"
    __table_args__ = (
        CheckConstraint("from_amount > 0", name="ck_transfer_from_amount_positive"),
        CheckConstraint("to_amount > 0", name="ck_transfer_to_amount_positive"),
        CheckConstraint(
            "from_account_id <> to_account_id", name="ck_transfer_distinct_accounts"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Design D36: NO ACTION, not RESTRICT, not CASCADE — see module docstring.
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.account.id", ondelete="NO ACTION"),
        nullable=False,
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.account.id", ondelete="NO ACTION"),
        nullable=False,
    )
    # Design D37: two stored amounts (not amount + rate) so a future P6
    # reads the destination credit directly instead of re-deriving it from
    # an account rate that may since have changed.
    from_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    to_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
