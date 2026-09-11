"""ORM models for the `transaction-templates` capability (design D45-D56,
D55). A template is a named, reusable income/expense SHAPE — never an
actual posted transaction — mirroring `app.transactions.models.Transaction`
+ `TransactionCategorySplit`'s exact split-allocation pattern (spec's
"Templates Support Optional Split Allocation" requirement).

Column shapes match the design's Interfaces/Contracts section exactly:

    app.transaction_template(id uuid pk,
        workspace_id uuid nn fk app.workspace.id on delete cascade,
        account_id   uuid nn fk app.account.id   on delete cascade,
        name text nn, position integer nn default 0,
        type text nn, amount numeric(18,2) nn, notes text null,
        created_by_user_id uuid nn fk app.app_user.id on delete cascade,
        created_at/updated_at timestamptz nn default now(),
        CHECK (type IN ('income','expense')), CHECK (amount > 0),
        UNIQUE (workspace_id, name))
    index: ix_transaction_template_workspace_id_position (workspace_id, position)

    app.transaction_template_split(id uuid pk,
        template_id uuid nn fk app.transaction_template.id on delete cascade,
        category_id uuid nn fk app.category.id on delete restrict,
        amount numeric(18,2) nn, CHECK (amount > 0),
        UNIQUE (template_id, category_id))

A template deliberately has NO `category_id` column of its own — exactly
like `Transaction` itself, category allocation lives entirely in the split
table (spec's own inference: "not explicit in the proposal's field list,
inferred from legacy `recurrent_income_or_expense.multi_category`
evidence"). A template also carries no `checked`/`is_refund` (R7 — these
are states of a POSTED row, meaningless on a reusable shape).

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0005_templates_and_recurring.py` migration
(design D11's precedent) — these classes exist so application code has a
typed model to query against, not so Alembic can autogenerate from them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TransactionTemplate(Base):
    __tablename__ = "transaction_template"
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_transaction_template_type"),
        CheckConstraint("amount > 0", name="ck_transaction_template_amount_positive"),
        UniqueConstraint("workspace_id", "name", name="uq_transaction_template_workspace_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.account.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Design decision 8: income|expense only, never transfer (P3's entity).
    type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class TransactionTemplateSplit(Base):
    __tablename__ = "transaction_template_split"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_template_split_amount_positive"),
        UniqueConstraint(
            "template_id", "category_id", name="uq_transaction_template_split_template_category"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.transaction_template.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
