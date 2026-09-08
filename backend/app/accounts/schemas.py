"""Pydantic request/response models for the `account-management`/
`account-visibility` capabilities (design's Interfaces/Contracts section,
design D19 money serialization).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Design D19: `numeric(18,2)`/`numeric(18,8)` DB columns, Python `Decimal`
# in application code, but serialized on the wire as a JSON STRING —
# binary floats cannot represent currency exactly, and a JSON string wire
# format keeps a JS client from silently re-introducing that error by
# parsing a JSON number straight into a JS `number`. Reused by
# `app.workspace.schemas`'s summary response (design D16) so both money
# surfaces share one serialization rule.
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: str(v), return_type=str)]

_ISO_4217_PATTERN = r"^[A-Z]{3}$"


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    owner_user_id: uuid.UUID | None
    name: str
    currency: str
    exchange_rate: MoneyOut
    initial_funds: MoneyOut
    is_personal: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


class AccountCreateIn(BaseModel):
    """`owner_user_id` is deliberately NOT an input field: a caller can
    only ever create a personal account owned by THEMSELVES
    (`app.accounts.service.create_account` derives ownership from the
    authenticated `WorkspaceScope`, never from the request body) — there
    is no path to attach a personal account to another member."""

    name: str
    currency: str = Field(pattern=_ISO_4217_PATTERN)
    exchange_rate: Decimal = Decimal(1)
    initial_funds: Decimal = Decimal(0)
    is_personal: bool = False


class AccountUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`).

    `is_personal`/`owner_user_id` are deliberately NOT here — the spec's
    account-management requirement names exactly
    name/currency/exchange_rate/initial_funds/`archived` as the mutable
    CRUD surface; the personal flag and owner are fixed at creation time.
    """

    name: str | None = None
    currency: str | None = Field(default=None, pattern=_ISO_4217_PATTERN)
    exchange_rate: Decimal | None = None
    initial_funds: Decimal | None = None
    archived: bool | None = None
