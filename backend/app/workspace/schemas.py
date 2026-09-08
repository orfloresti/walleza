"""Pydantic request/response models for the `workspace-membership`
capability (design's Interfaces/Contracts section), plus
`GET /api/workspace/summary`'s response shape (design D16, PR3 task 6.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

# Reuses `app.accounts.schemas`'s money-as-JSON-string serialization rule
# (design D19) so the summary's `total`/`grand_total` fields serialize
# identically to `AccountOut.exchange_rate`/`initial_funds` — one
# definition site, not a second parallel money type.
from app.accounts.schemas import MoneyOut


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    joined_at: datetime


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    members: list[MemberOut]


class WorkspaceRenameIn(BaseModel):
    name: str


class InviteCreateOut(BaseModel):
    """The raw, single-use invite token is embedded in `url` and returned
    exactly ONCE, on creation (design D12) — never persisted anywhere and
    never present again in any later response (spec RED #7)."""

    id: uuid.UUID
    url: str
    expires_at: datetime


class InviteListItemOut(BaseModel):
    """No `token`/`url` field on purpose — the list endpoint must never
    leak the raw token nor the stored hash (spec RED #7)."""

    id: uuid.UUID
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InviteAcceptIn(BaseModel):
    token: str


class CurrencyTotalOut(BaseModel):
    currency: str
    total: MoneyOut


class WorkspaceSummaryOut(BaseModel):
    """Design D16: computed by `app.accounts.service.compute_summary` as a
    SQL aggregate over the exact same `Select`
    `GET /api/accounts`'s default (`archived=false`) call uses — never a
    parallel/independent query that could drift from what the list
    endpoint shows."""

    by_currency: list[CurrencyTotalOut]
    grand_total: MoneyOut
