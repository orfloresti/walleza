"""Textract `AnalyzeExpense` client and response mapping (design D125,
D128, D129, D135). The `boto3` Textract client is created at MODULE
SCOPE (import time), mirroring `app/storage.py`'s `_s3_client` and
`app/db.py`'s engine (design D1) — built once at Lambda cold start, reused
across warm invocations, never rebuilt per-record.

`AnalyzeExpense`'s `Document={"S3Object": {...}}` input form means the
receipt bytes are never downloaded into this Lambda at all (design D127
step 2) — Textract reads the object directly from S3 on AWS's side.

Response shape (per AWS's documented `AnalyzeExpense` contract, matching
design D128's own field-name choices):

    {"ExpenseDocuments": [{"SummaryFields": [
        {"Type": {"Text": "TOTAL", ...},
         "ValueDetection": {"Text": "45.67", "Confidence": 98.5}},
        ...
    ]}]}

Only three `SummaryFields` types are mapped: `TOTAL` -> amount,
`INVOICE_RECEIPT_DATE` -> occurred_on, `VENDOR_NAME` -> vendor_name.
`extracted_currency` (design D118, advisory-only) is read from an
optional `CURRENCY`-typed summary field when Textract returns one; most
responses carry no such field, and this stays `None` in that case — never
inferred from a symbol embedded in `TOTAL`'s text, which would be guessing.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from dateutil import parser as dateutil_parser

from app.config import get_settings

_settings = get_settings()

_textract_client = boto3.client("textract", region_name=_settings.ocr_textract_region)

# Design D128: raised by AWS for a transient condition (network blip,
# throttling, a momentary service-side error) — worth retrying.
_TRANSIENT_ERROR_CODES = frozenset(
    {
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "InternalServerError",
    }
)

# Design D128: a deterministic property of the document itself. Retrying
# changes nothing, so these never retry.
_NON_RETRYABLE_DOCUMENT_ERROR_CODES = frozenset(
    {
        "UnsupportedDocumentException",
        "BadDocumentException",
        "DocumentTooLargeException",
        "InvalidParameterException",
    }
)

# Design D128: a misconfiguration (bad IAM policy, wrong credentials).
# Retrying is pure latency for an error that will not resolve itself
# in-process; classified as `provider_unavailable` because it is AWS-side,
# not a property of the user's photo.
_MISCONFIGURATION_ERROR_CODES = frozenset(
    {
        "AccessDeniedException",
        "UnrecognizedClientException",
    }
)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = (1.0, 2.0, 4.0)
_TOTAL_CONFIDENCE_FLOOR = 50.0


class TextractNonRetryableError(Exception):
    """Design D128: a document-shaped or misconfiguration error Textract
    raised that must NOT be retried. Carries the `failure_reason` the
    caller should store directly."""

    def __init__(self, *, failure_reason: str) -> None:
        super().__init__(failure_reason)
        self.failure_reason = failure_reason


class TextractRetriesExhaustedError(Exception):
    """Design D128/D129: every in-process attempt raised a transient
    error. The caller stores `failure_reason='provider_unavailable'` and
    `attempt_count=attempts`."""

    def __init__(self, *, attempts: int) -> None:
        super().__init__(f"Textract unavailable after {attempts} attempts")
        self.attempts = attempts


@dataclass(frozen=True)
class ExtractionResult:
    """The typed shape `app.ocr.extraction.process` writes into
    `TransactionOcrExtraction` (design D117). `status`/`failure_reason`
    already match that table's CHECK-constrained domain exactly."""

    status: str  # "succeeded" | "failed"
    failure_reason: str | None
    attempt_count: int
    extracted_amount: Decimal | None = None
    extracted_occurred_on: date | None = None
    extracted_vendor_name: str | None = None
    extracted_currency: str | None = None
    field_confidence: dict[str, float] = field(default_factory=dict)
    raw_response: dict[str, Any] | None = None


def _classify_client_error(exc: ClientError) -> str:
    code = exc.response.get("Error", {}).get("Code", "")
    if code in _TRANSIENT_ERROR_CODES:
        return "transient"
    if code in _MISCONFIGURATION_ERROR_CODES:
        return "misconfiguration"
    if code in _NON_RETRYABLE_DOCUMENT_ERROR_CODES:
        return "document"
    # An unrecognised Textract error code is treated as transient rather
    # than silently swallowed as a permanent document failure — an
    # unclassified AWS-side error deserves the same benefit of the doubt
    # (retry, then surface as provider_unavailable) as a known transient one.
    return "transient"


def _sleep_with_full_jitter(attempt_index: int) -> None:
    base = _BACKOFF_BASE_SECONDS[attempt_index]
    time.sleep(random.uniform(0, base))


def _call_once(*, bucket: str, key: str) -> dict[str, Any]:
    try:
        return _textract_client.analyze_expense(
            Document={"S3Object": {"Bucket": bucket, "Name": key}}
        )
    except ClientError as exc:
        kind = _classify_client_error(exc)
        if kind == "misconfiguration":
            raise TextractNonRetryableError(
                failure_reason="provider_unavailable"
            ) from exc
        if kind == "document":
            raise TextractNonRetryableError(
                failure_reason="unreadable_document"
            ) from exc
        raise  # transient — let the caller's retry loop handle it
    except (EndpointConnectionError, ReadTimeoutError):
        raise  # also transient (design D128)


def call_analyze_expense(*, bucket: str, key: str) -> dict[str, Any]:
    """Design D128/D129: up to `_MAX_ATTEMPTS` in-process attempts with
    exponential-backoff-with-full-jitter (`1s, 2s, 4s`) on a transient
    error, no retry on a document or misconfiguration error. Raises
    `TextractNonRetryableError` immediately for the latter, or
    `TextractRetriesExhaustedError` once every attempt has raised a
    transient error. Returns the raw Textract response dict on success."""
    last_transient: Exception | None = None
    for attempt_index in range(_MAX_ATTEMPTS):
        try:
            return _call_once(bucket=bucket, key=key)
        except TextractNonRetryableError:
            raise
        except (ClientError, EndpointConnectionError, ReadTimeoutError) as exc:
            # transient — every non-transient ClientError code was already
            # raised as `TextractNonRetryableError` by `_call_once` above.
            last_transient = exc
            if attempt_index < _MAX_ATTEMPTS - 1:
                _sleep_with_full_jitter(attempt_index)
    raise TextractRetriesExhaustedError(attempts=_MAX_ATTEMPTS) from last_transient


def _parse_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _parse_date(text: str) -> date | None:
    try:
        return dateutil_parser.parse(text).date()
    except (ValueError, OverflowError, TypeError):
        return None


def map_response(raw_response: dict[str, Any]) -> ExtractionResult:
    """Design D128's classification rule for the "200 but is it even a
    receipt" case, plus the field mapping for a genuine success.

    `no_receipt_detected` iff no `TOTAL` summary field is present at all,
    or its `ValueDetection.Confidence` is below `_TOTAL_CONFIDENCE_FLOOR`
    (50) — `TOTAL` is the single field the confirm flow genuinely cannot
    proceed without (a missing date defaults to today, a missing vendor
    leaves `notes` empty), so it is the sole discriminator rather than an
    arbitrary "average confidence" heuristic. Any other combination —
    including a `TOTAL` present with confidence anywhere from 50 up to
    99 — is a SUCCESS, with `field_confidence` stored verbatim so the
    frontend's separate 80%-threshold badge (design D134) can warn on a
    genuinely low-but-usable field without this function knowing about
    that threshold at all."""
    documents = raw_response.get("ExpenseDocuments") or []
    summary_fields: list[dict[str, Any]] = []
    for document in documents:
        summary_fields.extend(document.get("SummaryFields") or [])

    by_type: dict[str, dict[str, Any]] = {}
    for entry in summary_fields:
        type_text = (entry.get("Type") or {}).get("Text")
        if type_text:
            by_type[type_text] = entry

    total_field = by_type.get("TOTAL")
    total_confidence = (
        (total_field.get("ValueDetection") or {}).get("Confidence")
        if total_field
        else None
    )
    if (
        total_field is None
        or total_confidence is None
        or total_confidence < _TOTAL_CONFIDENCE_FLOOR
    ):
        return ExtractionResult(
            status="failed",
            failure_reason="no_receipt_detected",
            attempt_count=1,
            raw_response=raw_response,
        )

    field_confidence: dict[str, float] = {}
    extracted_amount: Decimal | None = None
    extracted_occurred_on: date | None = None
    extracted_vendor_name: str | None = None
    extracted_currency: str | None = None

    value = total_field.get("ValueDetection") or {}
    extracted_amount = _parse_decimal(value.get("Text", ""))
    field_confidence["amount"] = total_confidence

    date_field = by_type.get("INVOICE_RECEIPT_DATE")
    if date_field is not None:
        date_value = date_field.get("ValueDetection") or {}
        extracted_occurred_on = _parse_date(date_value.get("Text", ""))
        if date_value.get("Confidence") is not None:
            field_confidence["occurred_on"] = date_value["Confidence"]

    vendor_field = by_type.get("VENDOR_NAME")
    if vendor_field is not None:
        vendor_value = vendor_field.get("ValueDetection") or {}
        vendor_text = vendor_value.get("Text")
        if vendor_text:
            extracted_vendor_name = vendor_text
        if vendor_value.get("Confidence") is not None:
            field_confidence["vendor_name"] = vendor_value["Confidence"]

    currency_field = by_type.get("CURRENCY")
    if currency_field is not None:
        currency_text = (currency_field.get("ValueDetection") or {}).get("Text")
        if currency_text:
            extracted_currency = currency_text

    return ExtractionResult(
        status="succeeded",
        failure_reason=None,
        attempt_count=1,
        extracted_amount=extracted_amount,
        extracted_occurred_on=extracted_occurred_on,
        extracted_vendor_name=extracted_vendor_name,
        extracted_currency=extracted_currency,
        field_confidence=field_confidence,
        raw_response=raw_response,
    )


__all__ = [
    "ExtractionResult",
    "TextractNonRetryableError",
    "TextractRetriesExhaustedError",
    "call_analyze_expense",
    "map_response",
]
