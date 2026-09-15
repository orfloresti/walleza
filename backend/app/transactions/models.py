"""ORM models for the `transaction-management`/`transaction-splits`/
`transaction-attachments` capabilities (design D21-D27, D30, D33).

Column shapes match the design's Interfaces/Contracts section exactly:

    app.transaction(id uuid pk,
        workspace_id uuid nn fk app.workspace.id on delete cascade,
        account_id uuid nn fk app.account.id on delete cascade,
        type text nn, amount numeric(18,2) nn, occurred_on date nn, notes text null,
        is_refund boolean nn default false, checked boolean nn default false,
        photo_content_type text null, photo_uploaded_at timestamptz null,
        created_by_user_id uuid null fk app.app_user.id on delete set null,
        created_at timestamptz nn default now(), updated_at timestamptz nn default now(),
        CHECK (type IN ('income','expense')),              -- decision 8: no 'transfer'
        CHECK (amount > 0),                                -- sign lives in `type`, not the number
        CHECK ((photo_content_type IS NULL) = (photo_uploaded_at IS NULL)))
    indexes: ix_transaction_workspace_id_occurred_on (workspace_id, occurred_on DESC),
             ix_transaction_account_id

    app.transaction_category_split(id uuid pk,
        transaction_id uuid nn fk app.transaction.id on delete cascade,
        category_id uuid nn fk app.category.id on delete restrict,
        amount numeric(18,2) nn,
        CHECK (amount > 0),
        UNIQUE (transaction_id, category_id))
    index: ix_transaction_category_split_category_id

`occurred_on` rather than `date` — `date` is a Postgres type name and reads
badly in every filter expression (design's Interfaces/Contracts note).

`Transaction` carries **no visibility state of its own** (design's
Technical Approach / decision 6): its visibility is entirely inherited
from `account_id` via `visible_transactions(scope, ...)` (PR3), which
JOINs `visible_accounts(scope)` as a subquery — there is no
`is_personal`/`owner_user_id` column here to duplicate that predicate.

`TransactionCategorySplit.category_id` uses `ON DELETE RESTRICT` (design
D28, mirrored from `Category.parent_id`): a category referenced by a
historical split line cannot be deleted out from under that transaction's
allocation. `amount` on both `transaction` and
`transaction_category_split` is a positive-only `numeric(18,2)` Decimal
(design D19, D21) — the sum invariant across split lines is enforced at
the application layer only (design D22, PR3b's `service.replace_splits`),
never by a DB trigger.

Only the ORM shape lives here; the CHECK constraints and FKs are declared
for real in the hand-written `0003_categories_transactions.py` migration
(design D11's precedent) — these classes exist so application code has a
typed model to query against, not so Alembic can autogenerate from them.

Phase 9 (Photo-Based Expense Capture / OCR) adds `ocr_status` (design
D115), declared for real in `0012_ocr_drafts.py`. `OcrStatus` is a plain
`StrEnum`, not a native Postgres enum type (design D93's precedent,
mirrored by D115): the column is `Text` + CHECK. `NULL` means "an ordinary,
non-draft transaction" — the vast majority of existing and future rows —
so this column is additive and inert for every consumer that predates
Phase 9.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OcrStatus(StrEnum):
    """Design D115/D116 — transitions are enforced application-side via
    conditional `UPDATE ... WHERE ocr_status = <expected>`, never a DB
    trigger (design D116, D22's precedent). `CONFIRMED` is written only by
    the confirm endpoint; no worker path ever writes it."""

    PENDING_OCR = "pending_ocr"
    EXTRACTED = "extracted"
    EXTRACTION_FAILED = "extraction_failed"
    CONFIRMED = "confirmed"


class Transaction(Base):
    __tablename__ = "transaction"
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_transaction_type"),
        CheckConstraint("amount > 0", name="ck_transaction_amount_positive"),
        CheckConstraint(
            "(photo_content_type IS NULL) = (photo_uploaded_at IS NULL)",
            name="ck_transaction_photo_pair",
        ),
        CheckConstraint(
            "ocr_status IS NULL OR ocr_status IN "
            "('pending_ocr', 'extracted', 'extraction_failed', 'confirmed')",
            name="ck_transaction_ocr_status",
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
    # Design decision 8: income|expense only, never transfer (P3's entity).
    type: Mapped[str] = mapped_column(Text, nullable=False)
    # Design D19: numeric(18,2), Python Decimal — never float.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_refund: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    photo_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_uploaded_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    # Design D115: NULL means "not a photo-capture draft" — the default for
    # every pre-Phase-9 row and every manually-entered transaction.
    ocr_status: Mapped[str | None] = mapped_column(Text, nullable=True)


class TransactionCategorySplit(Base):
    __tablename__ = "transaction_category_split"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transaction_category_split_amount_positive"),
        UniqueConstraint(
            "transaction_id", "category_id", name="uq_transaction_category_split_txn_category"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.transaction.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Design D21: positive Decimal only — never a percentage, never a float.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
