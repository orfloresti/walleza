"""ORM models for the `recurring-transactions` capability (design D45-D56).
This PR is CRUD-only: `RecurringOccurrence` is created here because the
proposal's own File Changes table places all five Phase 4 tables in one
migration batch (design "Migration / Rollout"), but the write path that
populates it — `app.recurring.generation` — is a later PR's job. No route,
service function, or import in this package writes to it yet.

Column shapes match the design's Interfaces/Contracts section exactly:

    app.recurring_transaction(id uuid pk,
        workspace_id uuid nn fk app.workspace.id on delete cascade,
        account_id   uuid nn fk app.account.id   on delete cascade,
        type text nn, amount numeric(18,2) nn, notes text null,
        is_refund boolean nn default false, is_subscription boolean nn default false,
        repeat_every integer nn, period text nn,
        starts_on date nn,                       -- IMMUTABLE anchor (D49)
        occurrence_index integer nn default 0,   -- monotonic cursor (D47/D49)
        next_date date nn,                       -- cursor only, server-managed
        ends_on date null, reminder_days_before integer null,
        last_reminded_for_date date null, reminder_locale text nn default 'en',
        created_by_user_id uuid nn fk app.app_user.id on delete CASCADE,     -- D50
        created_at/updated_at timestamptz nn default now(),
        CHECK (type IN ('income','expense')), CHECK (amount > 0),
        CHECK (repeat_every >= 1), CHECK (period IN ('day','week','month','year')),
        CHECK (occurrence_index >= 0), CHECK (ends_on IS NULL OR ends_on >= starts_on),
        CHECK (reminder_days_before IS NULL OR reminder_days_before BETWEEN 0 AND 30),
        CHECK (reminder_locale IN ('en','es')))

    app.recurring_transaction_split(id uuid pk,
        recurring_transaction_id uuid nn fk app.recurring_transaction.id on delete cascade,
        category_id uuid nn fk app.category.id on delete restrict,
        amount numeric(18,2) nn, CHECK (amount > 0),
        UNIQUE (recurring_transaction_id, category_id))

    app.recurring_occurrence(
        recurring_transaction_id uuid nn fk app.recurring_transaction.id on delete cascade,
        occurrence_date date nn,
        transaction_id uuid null fk app.transaction.id on delete SET NULL,
        generated_at timestamptz nn default now(),
        PRIMARY KEY (recurring_transaction_id, occurrence_date))

Design D50: `created_by_user_id` is NOT NULL/`ON DELETE CASCADE` here —
deliberately unlike `transaction.created_by_user_id` (nullable/`SET NULL`)
— because a scheduled-generation run (a later PR) derives its whole
`WorkspaceScope` from this column; a recurrence whose creator no longer
exists has no valid scope and should not survive.

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0005_templates_and_recurring.py` migration
(design D11's precedent) — these classes exist so application code has a
typed model to query against, not so Alembic can autogenerate from them.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RecurringTransaction(Base):
    __tablename__ = "recurring_transaction"
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_recurring_transaction_type"),
        CheckConstraint("amount > 0", name="ck_recurring_transaction_amount_positive"),
        CheckConstraint(
            "repeat_every >= 1", name="ck_recurring_transaction_repeat_every_positive"
        ),
        CheckConstraint(
            "period IN ('day', 'week', 'month', 'year')",
            name="ck_recurring_transaction_period",
        ),
        CheckConstraint(
            "occurrence_index >= 0",
            name="ck_recurring_transaction_occurrence_index_non_negative",
        ),
        CheckConstraint(
            "ends_on IS NULL OR ends_on >= starts_on",
            name="ck_recurring_transaction_ends_on_after_starts_on",
        ),
        CheckConstraint(
            "reminder_days_before IS NULL OR reminder_days_before BETWEEN 0 AND 30",
            name="ck_recurring_transaction_reminder_days_before_range",
        ),
        CheckConstraint(
            "reminder_locale IN ('en', 'es')", name="ck_recurring_transaction_reminder_locale"
        ),
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
    # Design decision 8: income|expense only, never transfer (R2).
    type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_subscription: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    repeat_every: Mapped[int] = mapped_column(Integer, nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_date: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminder_days_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_reminded_for_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reminder_locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    # Design D50: NOT NULL, CASCADE — unlike transaction.created_by_user_id.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class RecurringTransactionSplit(Base):
    __tablename__ = "recurring_transaction_split"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_recurring_transaction_split_amount_positive"),
        UniqueConstraint(
            "recurring_transaction_id",
            "category_id",
            name="uq_recurring_transaction_split_recurring_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    recurring_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.recurring_transaction.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)


class RecurringOccurrence(Base):
    """The idempotency AUTHORITY for occurrence generation (design D47) —
    written by a later PR's `app.recurring.generation`, not by this one.
    Declared here only so the ORM model and the migration stay in sync."""

    __tablename__ = "recurring_occurrence"

    recurring_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.recurring_transaction.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurrence_date: Mapped[date] = mapped_column(Date, primary_key=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.transaction.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
