"""ORM model for the `category-management` capability (design D21, D28,
D29).

Column shape matches the design's Interfaces/Contracts section exactly:

    app.category(id uuid pk,
        workspace_id uuid nn fk app.workspace.id on delete cascade,
        parent_id uuid null fk app.category.id on delete restrict,
        name text nn, icon text null, type text nn,
        created_at timestamptz nn default now(), updated_at timestamptz nn default now(),
        CHECK (type IN ('income','expense')),
        CHECK (parent_id IS NULL OR parent_id <> id))
    index: ix_category_workspace_id

`parent_id` is a self-referencing FK with `ON DELETE RESTRICT` (design
D28): cascading a parent category would silently delete its children
**and** the split-allocation lines of historical transactions referencing
those children, which is money-data loss from a settings screen. The
service layer (PR2) catches the resulting `IntegrityError` and returns
409, naming the blocker; 404 stays reserved for invisible rows (D18).

Hierarchy depth is capped at exactly two levels (design D29): the DB-level
`ck_category_no_self_parent` CHECK only prevents a direct self-reference
cycle; the "a child's parent must itself be top-level" rule is enforced
by the service layer (PR2), not by DDL, since expressing "my parent's
parent must be NULL" as a CHECK constraint would require a self-join the
CHECK clause cannot express.

Only the ORM shape lives here; the CHECK constraints and FK are declared
for real in the hand-written `0003_categories_transactions.py` migration
(design D11's precedent, continued from `0002_workspace_accounts.py`) —
this class exists so application code has a typed model to query
against, not so Alembic can autogenerate from it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Category(Base):
    __tablename__ = "category"
    __table_args__ = (
        CheckConstraint("type IN ('income', 'expense')", name="ck_category_type"),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_category_no_self_parent"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.workspace.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app.category.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Design decision 8: income|expense only, never transfer (P3's entity).
    type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
