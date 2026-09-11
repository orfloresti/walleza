"""Pydantic request/response models for the `transaction-templates`
capability (design's Interfaces/Contracts section, design D19 money
serialization, D55, D56). Mirrors `app.transactions.schemas` closely — a
template is a reusable SHAPE, so it adds `name`/`position` and drops
`occurred_on`/`checked`/`is_refund` (R7: neither is settable on a template).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.accounts.schemas import MoneyOut

# Design decision 8: income|expense only, never transfer (P3's entity).
TemplateType = Literal["income", "expense"]


class TemplateSplitIn(BaseModel):
    """One allocation line in the inline `splits` request field — mirrors
    `app.transactions.schemas.SplitIn` exactly. `category_id` MUST
    reference a category the caller can already see
    (`app.categories.queries.visible_categories`) — enforced by
    `app.templates.service.replace_template_splits`, not here."""

    category_id: uuid.UUID
    amount: Decimal


class TemplateSplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    amount: MoneyOut


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    account_id: uuid.UUID
    name: str
    position: int
    type: TemplateType
    amount: MoneyOut
    notes: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    splits: list[TemplateSplitOut] = []


class TemplateCreateIn(BaseModel):
    """`account_id` MUST reference an account the caller can already see
    (`app.accounts.queries.visible_accounts`) — enforced by
    `app.templates.service.create_template`, not here, mirroring
    `app.transactions.schemas.TransactionCreateIn` exactly.

    No `checked`/`is_refund`/`occurred_on` field exists here at all (R7):
    a template is a reusable shape, not a posted row."""

    name: str
    account_id: uuid.UUID
    type: TemplateType
    amount: Decimal
    notes: str | None = None
    position: int = 0
    splits: list[TemplateSplitIn] | None = None


class TemplateUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`),
    mirroring `app.transactions.schemas.TransactionUpdateIn`.

    `splits`, when present in the request body at all (including an
    explicit empty list), REPLACES the whole existing split set — never
    additive (mirrors design D22's convention, applied identically here)."""

    name: str | None = None
    account_id: uuid.UUID | None = None
    type: TemplateType | None = None
    amount: Decimal | None = None
    notes: str | None = None
    position: int | None = None
    splits: list[TemplateSplitIn] | None = None


class TemplateApplyIn(BaseModel):
    """Design D56: the ONLY accepted override on apply is `occurred_on`
    (defaulting to today when omitted) — every other field is taken from
    the template verbatim. The template row itself is never modified by
    an apply."""

    occurred_on: date | None = None
