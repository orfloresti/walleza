"""SESv2 client wrapper for the `recurring-reminders` capability (design
D52-D54). Mirrors `app/storage.py`'s exact pattern (that module's own
docstring, and design's own File Changes table entry for this file): the
`boto3` client is a MODULE-SCOPE object, built once at import time, so
tests can monkeypatch it as a plain module attribute
(`monkeypatch.setattr(ses, "sesv2", fake_client)`) rather than reaching
into a function-local or class-wrapped client that hides the binding.

`boto3.client(...)` never opens a network connection at construction time,
so importing this module is always safe — including with no AWS
credentials configured at all (this sandbox, CI, a plain `ruff`/module
import, etc.), exactly as `app/storage.py`'s docstring establishes for its
own `_s3_client`.
"""

from __future__ import annotations

import boto3

from app.config import get_settings

_settings = get_settings()

# Module-scope cached client, mirroring app/storage.py's `_s3_client`
# (design D32's precedent, reused here for D54). Built once at Lambda cold
# start, reused across warm invocations of the same execution environment.
sesv2 = boto3.client("sesv2", region_name=_settings.ses_region)


def send_email(*, to_address: str, subject: str, body_text: str) -> None:
    """One SESv2 `SendEmail` call, `Simple` content, exactly ONE recipient
    (design D54: a reminder is never fanned out to more than the
    recurrence's own creator). `FromEmailAddress` is pinned to
    `settings.ses_from_address` — the exact address design D53's IAM
    `ses:FromAddress` condition permits `aws_iam_role.scheduler_exec` to
    send as; any other From address is rejected by IAM before SES is even
    reached, so this function cannot accidentally widen the sender.

    Raises whatever `sesv2.send_email` raises (e.g. a transient throttle).
    The caller (`app.recurring.generation`'s reminder pass) is the layer
    that decides what "send failed" means for the idempotency mark — this
    function stays a single, honest, unit-testable SES call, mirroring
    `app.storage.delete_object`'s "the caller owns the try/except"
    discipline."""
    sesv2.send_email(
        FromEmailAddress=_settings.ses_from_address,
        Destination={"ToAddresses": [to_address]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body_text, "Charset": "UTF-8"}},
            }
        },
    )
