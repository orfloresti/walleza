"""The non-HTTP entry point for the `photo-based-expense-capture`
capability's OCR worker (design D125).

Deployed as a SEPARATE Lambda function (`walleza-ocr-<env>`, handler
`app.ocr_worker.handler`) built from the same zip as the backend,
invoked ONLY by the receipts bucket's `aws_s3_bucket_notification` on
`ObjectCreated:*` (design D136 — Unit 7's infra, not this unit's
concern). This module deliberately never imports `app.main`, `mangum`,
or anything ASGI-shaped, exactly mirroring `app/scheduler.py`'s own
module docstring and structural isolation from the HTTP Lambda.

`event["Records"]` is attacker-influenceable input (design's threat
matrix: "Untrusted event input -> key injection/traversal", "Cross-tenant
write via forged workspace/transaction id in a key") — unlike
`app/scheduler.py`, which reads NO field of its event at all, this
worker MUST read `Records[].s3.object.key`, so that key is a real trust
boundary. `storage.parse_receipt_object_key` (design D126) is the sole
parser, and a non-matching or unparseable key is silently skipped —
never guessed at, never logged with its contents.

One `SessionLocal()` session PER RECORD, not per invocation (design
D125): an S3 event batch is ~1 record in practice, but this guarantees
one poisoned record's failure can never roll back a sibling record's
already-committed work.
"""

from __future__ import annotations

from contextlib import closing
from typing import Any
from urllib.parse import unquote_plus

from app import storage
from app.db import SessionLocal
from app.ocr import extraction


def handler(event: Any, context: Any) -> dict[str, int]:
    """Entry point invoked by the S3 bucket notification (design D136).
    `context` is unused, kept only to match the Lambda handler signature.
    Returns `{"processed": ..., "skipped": ...}` for CloudWatch log
    inspection only — never consumed by any caller."""
    processed = 0
    skipped = 0

    for record in event.get("Records", []):
        s3_info = record.get("s3", {})
        raw_key = s3_info.get("object", {}).get("key")
        bucket_name = s3_info.get("bucket", {}).get("name")
        if raw_key is None or bucket_name is None:
            skipped += 1
            continue

        # S3 event keys are URL-encoded (e.g. a literal `+` for a space);
        # `receipt_object_key`'s format never contains either, but this
        # matches the standard, documented S3-event decoding step so a
        # future key shape does not silently break on this alone.
        key = unquote_plus(raw_key)

        parsed = storage.parse_receipt_object_key(key)
        if parsed is None:
            skipped += 1
            continue
        workspace_id, transaction_id = parsed

        with closing(SessionLocal()) as db:
            if extraction.process(
                db, workspace_id=workspace_id, transaction_id=transaction_id, key=key
            ):
                processed += 1
            else:
                skipped += 1

    return {"processed": processed, "skipped": skipped}
