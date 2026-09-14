"""Pydantic request/response models for the `report-category-breakdown`
and `report-default-currency` capabilities (design D88).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

# Design D19/D88: `numeric(18,2)` DB column, Python `Decimal` in
# application code, but serialized on the wire as a JSON STRING — mirrors
# `app.budgets.schemas.MoneyOut` exactly.
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]


class CategorySliceOut(BaseModel):
    """`own` and `total` are exposed as SEPARATE fields (design D81) —
    never collapsed into one number, since that would make a
    parent-double-counting bug undetectable by inspection."""

    category_id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    own: MoneyOut
    total: MoneyOut


class CategoryBreakdownOut(BaseModel):
    currency: str
    date_from: date
    date_to: date
    slices: list[CategorySliceOut]


class DefaultCurrencyOut(BaseModel):
    currency: str | None
