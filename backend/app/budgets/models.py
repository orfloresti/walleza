"""ORM model for the `budget-management` capability (design D66-D69).

Column shape matches the design's Interfaces/Contracts section exactly:

    app.budget(id uuid pk,
        workspace_id uuid nn fk app.workspace.id on delete cascade,
        category_id  uuid nn fk app.category.id  on delete restrict,
        account_id   uuid null fk app.account.id on delete cascade,
        name text null,
        amount numeric(18,2) nn,
        currency text nn,
        created_at timestamptz nn default now(), updated_at timestamptz nn default now(),
        CHECK (amount > 0),
        CHECK (currency ~ '^[A-Z]{3}$'))
    indexes: ix_budget_workspace_id, ix_budget_category_id

`category_id` is `ON DELETE RESTRICT` (design D67): matches every other
category reference in the codebase (D28) — deleting a category still
referenced by a budget is blocked with a 409 by
`app.categories.service.delete_category`'s existing `IntegrityError`
handling, no code change needed there beyond widening its message.

`account_id` is `ON DELETE CASCADE`, not `SET NULL` (design D68): a
`SET NULL` would silently widen an account-scoped budget into an
all-accounts budget, changing its meaning without the user acting;
deleting the watched account deletes the budget that only existed to
watch it.

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0006_budgets.py` migration (design D11's
precedent) — this class exists so application code has a typed model to
query against, not so Alembic can autogenerate from it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Budget(Base):
    __tablename__ = "budget"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_budget_amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_budget_currency_iso4217"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.account.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    # Design D66/D19: plain ISO 4217 text, no lookup/enum table — mirrors
    # `Account.currency` exactly.
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
