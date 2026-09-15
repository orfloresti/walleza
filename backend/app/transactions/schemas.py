"""Pydantic request/response models for the `transaction-management`/
`transaction-splits`/`transaction-attachments` capabilities (design's
Interfaces/Contracts section, design D19 money serialization, D21/D22/D33,
D24/D25/D26). PR3b added the inline `splits` field (spec's
Interfaces/Contracts note: splits are modeled inline in the transaction
payload, never a separate sub-resource). PR5 adds the photo
upload-url/confirm/download request/response shapes — `Transaction`'s own
`photo_content_type`/`photo_uploaded_at` fields (already on `TransactionOut`
since PR1) stay read-only; a photo is never written through the
transaction payload itself (spec's "API MUST NOT accept photo bytes in the
transaction request body").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.accounts.schemas import MoneyOut

# Design decision 8: income|expense only, never transfer (P3's entity).
TransactionType = Literal["income", "expense"]

# Design D25: the exact allowlisted `Content-Type`s a receipt photo may
# declare. A `Literal` here means Pydantic itself rejects an out-of-list
# declaration with a 422 before any presigned URL is ever generated — the
# service layer/`app.storage` never has to re-check this specific case.
PhotoContentType = Literal["image/jpeg", "image/png", "image/webp", "image/heic"]


class SplitIn(BaseModel):
    """One allocation line in the inline `splits` request field (design
    D21: a positive Decimal amount only, never a percentage or a float).
    `category_id` MUST reference a category the caller can already see
    (`app.categories.queries.visible_categories`) — enforced by
    `app.transactions.service.replace_splits`, not here, since it
    requires a database lookup."""

    category_id: uuid.UUID
    amount: Decimal


class SplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    amount: MoneyOut


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    account_id: uuid.UUID
    type: TransactionType
    amount: MoneyOut
    occurred_on: date
    notes: str | None
    is_refund: bool
    checked: bool
    photo_content_type: str | None
    photo_uploaded_at: datetime | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    # Design D21/D22 — a whole-set snapshot of this transaction's current
    # split lines. Empty list is a legal state ("uncategorized").
    splits: list[SplitOut] = []


class TransactionCreateIn(BaseModel):
    """`account_id` MUST reference an account the caller can already see
    (`app.accounts.queries.visible_accounts`) — enforced by
    `app.transactions.service.create_transaction`, not here, since it
    requires a database lookup. An account id from another workspace, or
    another member's personal account in the SAME workspace, is rejected
    exactly as if it did not exist (mirrors
    `app.categories.service._validate_parent_reference`'s cross-workspace
    `parent_id` handling — never silently accept a foreign-scope id).

    `splits` is optional (design D21: zero lines is legal, "uncategorized").
    When present, every line's `category_id` must resolve inside the
    caller's workspace and the lines must sum EXACTLY to `amount`
    (design D22) — enforced by `service.replace_splits`, never here."""

    account_id: uuid.UUID
    type: TransactionType
    amount: Decimal
    occurred_on: date
    notes: str | None = None
    is_refund: bool = False
    checked: bool = False
    splits: list[SplitIn] | None = None


class TransactionUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`),
    mirroring `app.accounts.schemas.AccountUpdateIn` /
    `app.categories.schemas.CategoryUpdateIn`. When `account_id` is
    present, it is re-validated exactly like on create.

    `splits`, when present in the request body at all (including an
    explicit empty list), REPLACES the whole existing split set — never
    additive, never a partial edit (design D22). When `splits` is absent
    from the request body, existing split lines are left untouched,
    UNLESS `amount` is also being changed: the service layer then
    re-validates that the untouched splits still sum to the new amount
    and rejects the update if they no longer do (spec: "Updating amount
    without updating splits is rejected")."""

    account_id: uuid.UUID | None = None
    type: TransactionType | None = None
    amount: Decimal | None = None
    occurred_on: date | None = None
    notes: str | None = None
    is_refund: bool | None = None
    checked: bool | None = None
    splits: list[SplitIn] | None = None


class PhotoUploadUrlIn(BaseModel):
    """Design D24 step ②: the caller declares the photo's `Content-Type`
    up front. The actual byte SIZE is bounded by the presigned POST
    policy's own `content-length-range` condition (design D25) — enforced
    by S3 itself at upload time, never by a client-declared size field
    here (a client cannot be trusted to declare its own upload's true
    size; S3's own enforcement is the only trustworthy bound)."""

    content_type: PhotoContentType


class PhotoUploadUrlOut(BaseModel):
    """The `generate_presigned_post` payload (design D24/D25) plus the two
    values the browser's multipart upload and the UI both need:
    `max_bytes` (so the UI can pre-validate a file before even attempting
    to upload) and `content_type` (echoed back so the caller need not
    separately track what it just declared)."""

    url: str
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int
    content_type: PhotoContentType


class PhotoConfirmIn(BaseModel):
    """The SAME `Content-Type` the caller declared when requesting the
    upload URL. `service.confirm_photo_upload` stores it verbatim as
    `photo_content_type` only once `app.storage.object_exists` proves the
    object is genuinely there (design D24 step ④) — a confirm with no
    object actually uploaded is rejected (409) before this value is ever
    written."""

    content_type: PhotoContentType


class PhotoConfirmOut(BaseModel):
    photo_content_type: PhotoContentType
    photo_uploaded_at: datetime


class PhotoDownloadUrlOut(BaseModel):
    url: str
    expires_at: datetime


class DraftFromPhotoIn(BaseModel):
    """Design D119: `account_id` is a REQUIRED request field — the draft
    row is inserted with a placeholder `amount=0.01` and no splits, so the
    only piece of caller-provided state at this step is which account the
    eventual transaction belongs to. `content_type` reuses the same
    allowlist `PhotoUploadUrlIn` already enforces (design D25)."""

    account_id: uuid.UUID
    content_type: PhotoContentType


class DraftFromPhotoOut(BaseModel):
    """Design D131: the presigned-upload payload (identical shape to
    `PhotoUploadUrlOut`) plus the newly created draft transaction's id, so
    the caller can immediately start polling `GET
    /api/transactions/{id}/ocr` once the upload completes."""

    transaction_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_at: datetime
    max_bytes: int
    content_type: PhotoContentType


class OcrExtractionOut(BaseModel):
    """Design D131's poll response shape for a `transaction_ocr_extraction`
    row. `raw_response` is deliberately never exposed (design D117's
    privacy rule) — only the typed fields Textract mapped, plus per-field
    `field_confidence`. A key ABSENT from `field_confidence` means the
    worker never returned that field at all (distinct from a low but
    present confidence — the UI must treat the two differently, design
    D134)."""

    status: Literal["succeeded", "failed"]
    failure_reason: (
        Literal["provider_unavailable", "unreadable_document", "no_receipt_detected"] | None
    )
    amount: MoneyOut | None
    occurred_on: date | None
    vendor_name: str | None
    currency: str | None
    field_confidence: dict[str, float]


class OcrStatusOut(BaseModel):
    """Design D131: `GET /api/transactions/{id}/ocr` response. `extraction`
    is `null` while the transaction is still `pending_ocr` (the worker has
    not written a row yet) — the poller (design D132) reads `ocr_status`
    alone to decide whether to keep polling."""

    ocr_status: Literal["pending_ocr", "extracted", "extraction_failed", "confirmed"]
    extraction: OcrExtractionOut | None
