"""Pydantic request/response models for the `transfer-management`
capability (design's Interfaces/Contracts section, D19/D40/D43/D44).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.accounts.schemas import MoneyOut


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    from_amount: MoneyOut
    to_amount: MoneyOut
    occurred_on: date
    notes: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TransferCreateIn(BaseModel):
    """Design D40/spec: NO `to_amount` field — the server always derives
    it (`app.transfers.service._derive_to_amount`), never accepts one
    from the client; the TYPE having no such field is how "server-derived"
    is enforced, not a runtime check.

    No `extra="forbid"` set here either, matching every other schema in
    this codebase (`app.transactions.schemas`, `app.accounts.schemas`,
    `app.categories.schemas` — none of which sets it): a client-sent
    `to_amount` in the request body is silently ignored by Pydantic's
    default "ignore unknown fields" behavior rather than rejected — the
    spec's explicit resolution of this exact question.

    No `category_id`/`splits`/equivalent field either (design T5): a
    transfer is a balance move, not a categorized income or expense."""

    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    from_amount: Decimal
    occurred_on: date
    notes: str | None = None
