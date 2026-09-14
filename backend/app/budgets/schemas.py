"""Pydantic request/response models for the `budget-management`/
`budget-progress` capabilities (design's Interfaces/Contracts section).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Design D19/D66: `numeric(18,2)` DB column, Python `Decimal` in
# application code, but serialized on the wire as a JSON STRING — mirrors
# `app.accounts.schemas.MoneyOut` exactly (binary floats cannot represent
# currency exactly, and a JSON string wire format keeps a JS client from
# silently re-introducing that error).
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    category_id: uuid.UUID
    account_id: uuid.UUID | None
    name: str | None
    amount: MoneyOut
    currency: str
    created_at: datetime
    updated_at: datetime


class BudgetCreateIn(BaseModel):
    """`category_id` is required; `account_id` is optional (category-only
    budget when omitted). Referential validity (category/account exist and
    are visible in the caller's workspace) and the account-currency-match
    rule (design D73) require a database lookup and are enforced by
    `app.budgets.service.create_budget`, not here."""

    category_id: uuid.UUID
    account_id: uuid.UUID | None = None
    name: str | None = None
    amount: Decimal = Field(gt=0)
    # Design D66: plain ISO 4217 text, no lookup/enum table — mirrors
    # `app.accounts.models.Account.currency`'s CHECK exactly.
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class BudgetProgressOut(BaseModel):
    """Current-month progress for one budget (design D71-D78). Never
    persisted — computed live on every read from `visible_transactions`,
    so this shape carries no `id`/timestamps of its own."""

    limit: MoneyOut
    spent: MoneyOut
    remaining: MoneyOut
    percent: float
    status: Literal["on_track", "near_limit", "over_budget"]
    period_start: date
    period_end: date


class BudgetWithProgressOut(BudgetOut):
    """`BudgetOut` plus its current-month `progress` (design's
    Interfaces/Contracts table: every budget route returns this shape, not
    the bare CRUD `BudgetOut`)."""

    progress: BudgetProgressOut


class BudgetUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`),
    mirroring `app.categories.schemas.CategoryUpdateIn`. Setting
    `account_id` to `null` explicitly detaches a budget back to
    category-only; omitting it entirely leaves the current `account_id`
    untouched."""

    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    name: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
