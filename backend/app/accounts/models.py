"""ORM model for the `account-management`/`account-visibility` capabilities
(design D15, D19).

Column shape matches the design's Interfaces/Contracts section exactly:

    app.account(id uuid pk,
                workspace_id uuid nn fk app.workspace.id on delete cascade,
                owner_user_id uuid null fk app.app_user.id on delete restrict,
                name text nn, currency text nn,
                exchange_rate numeric(18,8) nn default 1,
                initial_funds numeric(18,2) nn default 0,
                is_personal boolean nn default false,
                archived boolean nn default false,
                created_at timestamptz nn default now(),
                updated_at timestamptz nn default now(),
                CHECK (currency ~ '^[A-Z]{3}$'),
                CHECK (exchange_rate > 0),
                CHECK (NOT is_personal OR owner_user_id IS NOT NULL))

`owner_user_id` is nullable (shared accounts have no owner) but uses
`ON DELETE RESTRICT`, not `SET NULL`: a `SET NULL` on a personal account's
owner would violate the "personal accounts must have an owner" CHECK below.
User deletion is out of scope for Phase 1 (design "Data Flow" note).

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0002_workspace_accounts.py` migration
(design D11) — this class exists so application code has a typed model to
query against, not so Alembic can autogenerate from it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_account_currency_iso4217"),
        CheckConstraint("exchange_rate > 0", name="ck_account_exchange_rate_positive"),
        CheckConstraint(
            "NOT is_personal OR owner_user_id IS NOT NULL",
            name="ck_account_personal_requires_owner",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Design D19/decision 7: plain ISO 4217 text, no lookup/enum table.
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    # Design D19: numeric(18,8)/numeric(18,2), Python Decimal — never float.
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False, server_default="1"
    )
    initial_funds: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0"
    )
    is_personal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
