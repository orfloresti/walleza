"""Pydantic request/response models for the `category-management`
capability (design's Interfaces/Contracts section).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Design decision 8 / D29: exactly `income`/`expense` on categories too —
# there is no `transfer` category, matching the transaction type enum.
CategoryType = Literal["income", "expense"]


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    icon: str | None
    type: CategoryType
    created_at: datetime
    updated_at: datetime


class CategoryCreateIn(BaseModel):
    """`parent_id` is optional (top-level category when omitted). Design
    D29: when present, the referenced category must exist in the caller's
    own workspace and must itself be top-level (`parent_id IS NULL`) —
    enforced by `app.categories.service.create_category`, not here, since
    it requires a database lookup."""

    name: str
    icon: str | None = None
    type: CategoryType
    parent_id: uuid.UUID | None = None


class CategoryUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`),
    mirroring `app.accounts.schemas.AccountUpdateIn`. Setting `parent_id`
    to `null` explicitly detaches a category from its parent; omitting it
    entirely leaves the current `parent_id` untouched."""

    name: str | None = None
    icon: str | None = None
    type: CategoryType | None = None
    parent_id: uuid.UUID | None = None
