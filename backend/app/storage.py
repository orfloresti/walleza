"""S3 access for the `transaction-attachments` capability (design D23-D27,
D32). Sibling of `app/deps.py`/`app/security.py` — one definition site for
the receipt-photo key convention and the only place `boto3` is ever
imported in application code.

The `boto3` client is created at MODULE SCOPE (import time), mirroring
`app/db.py`'s engine (design D1): built once at Lambda cold start, reused
across warm invocations of the same execution environment, never rebuilt
per-request or per-dependency. `boto3.client(...)` itself never opens a
network connection at construction time, so importing this module is
always safe, including with no AWS credentials configured at all (this
sandbox, CI, a plain `ruff`/module import, etc.).

`receipt_object_key` is a PURE FUNCTION of `(workspace_id, transaction_id)`
— deterministic, no persistence, no key column stored anywhere on the
`transaction` row (design D23). This is what lets `confirm_photo_upload`/
`request_photo_download_url` (`app/transactions/service.py`) take no key
parameter at all: a caller can never name a foreign object to link or
read, and a re-upload overwrites the SAME key in place (no
orphan-per-replacement).

Presigning (`presigned_upload`/`presigned_download`) is a pure OFFLINE
signing operation — no network call reaches AWS to produce a presigned
URL — so both are unit-testable with no real AWS and no `moto` (design
D32): a test can mock the module-scope client and assert on the exact
arguments passed to it.
"""

from __future__ import annotations

import uuid

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import get_settings

_settings = get_settings()

# Module-scope cached client (design D32, mirroring `app/db.py`'s engine,
# D1). `signature_version="s3v4"` is required for `generate_presigned_post`
# to embed both `content-length-range` and an exact `Content-Type`
# condition in the policy it signs.
_s3_client = boto3.client(
    "s3",
    region_name=_settings.s3_region,
    config=BotoConfig(signature_version="s3v4"),
)


def receipt_object_key(workspace_id: uuid.UUID, transaction_id: uuid.UUID) -> str:
    """Design D23: fully deterministic — a pure function of two uuid4s, no
    persistence, no key column on the `transaction` row. Two uuid4s in the
    path is non-guessable on its own; the bucket is private regardless
    (public-access-block + `BucketOwnerEnforced`, `infra/s3.tf`). A
    re-upload targets this SAME key, overwriting in place — there is no
    per-replacement orphan to clean up."""
    return f"workspaces/{workspace_id}/transactions/{transaction_id}/receipt"


def presigned_upload(*, key: str, content_type: str) -> dict[str, object]:
    """Design D25: `generate_presigned_post`, deliberately never a
    presigned PUT — a PUT cannot bound size or type at S3, only a POST
    policy can. `Conditions` enforces BOTH `content-length-range` and an
    EXACT `Content-Type` at S3 itself, before any byte is ever stored or
    billed — a caller declaring an oversized or wrong-type upload is
    rejected by these conditions at S3, never by a post-hoc check here.

    Returns the raw `{"url": ..., "fields": {...}}` payload
    `generate_presigned_post` produces; the caller
    (`app.transactions.service.request_photo_upload_url`) adds the
    `expires_at`/`max_bytes`/`content_type` values the response schema
    also carries.
    """
    return _s3_client.generate_presigned_post(
        Bucket=_settings.s3_receipts_bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, _settings.receipt_max_bytes],
        ],
        ExpiresIn=_settings.presigned_url_ttl_seconds,
    )


def presigned_download(*, key: str, content_type: str) -> str:
    """A presigned GET. `ResponseContentType` is pinned server-side from
    the caller-supplied (i.e. the STORED `photo_content_type` column's)
    value, never echoed from the object's own metadata (design D26) —
    attacker-controlled bytes never get to choose how a browser renders
    them. `ResponseContentDisposition=inline` on a bucket that is never a
    same-origin host for the app (design's Threat Matrix note)."""
    return _s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": _settings.s3_receipts_bucket,
            "Key": key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=_settings.presigned_url_ttl_seconds,
    )


def object_exists(*, key: str) -> bool:
    """A `head_object` call — used by the confirm endpoint
    (`app.transactions.service.confirm_photo_upload`) to verify an upload
    actually landed before ever marking `photo_uploaded_at`. ANY
    `ClientError` (object not found, or otherwise) is treated as "does not
    exist"; the caller maps that to a 409, never a crash on a transient
    S3-side hiccup."""
    try:
        _s3_client.head_object(Bucket=_settings.s3_receipts_bucket, Key=key)
    except ClientError:
        return False
    return True


def delete_object(*, key: str) -> None:
    """One `delete_object` call — deliberately NOT wrapped in a
    try/except here. Design D27's "best-effort, does not fail the
    request" semantics belong to the CALLER
    (`app.transactions.router.delete_transaction`), which runs this AFTER
    its own DB delete has already committed: that is the only place that
    knows the DB delete already succeeded and must never be rolled back,
    retried, or turned into a failed response for an S3-side error. This
    function itself stays a single, honest, unit-testable S3 call — a
    test can mock it to raise and assert the caller swallows it."""
    _s3_client.delete_object(Bucket=_settings.s3_receipts_bucket, Key=key)
