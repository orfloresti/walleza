"""The non-HTTP entry point for the `scheduled-occurrence-generation`
capability (design D45).

This module is deployed as a SEPARATE Lambda function (`walleza-scheduler-
<env>`, handler `app.scheduler.handler`) built from the same zip as the
backend, invoked ONLY by its own EventBridge rule (design D51, PR3's
job). It deliberately never imports `app.main`, `mangum`, or anything
ASGI-shaped — `app/handler.py` (the HTTP Lambda's entry point) and this
module do not share a single line of runtime code beyond the database
session and settings, by construction, so unreachability from the public
Function URL is a property of the deployment topology, not a code branch
that could regress.

`handler(event, context)` reads NO field of `event` at all (design's
threat case 2: a crafted payload naming a victim workspace/recurrence/
`today` must have zero effect). `today` always comes from the real clock
here — `app.recurring.generation.run` takes it as an explicit parameter
so tests never depend on wall-clock time.
"""

from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from typing import Any

from app.db import SessionLocal
from app.recurring import generation


def handler(event: Any, context: Any) -> dict[str, int]:
    """Entry point invoked by the EventBridge rule (design D51). `event`
    and `context` are the AWS Lambda invocation arguments; neither is
    read, by design — see the module docstring and design's threat case
    2. Returns the same summary dict `generation.run` returns, useful only
    for CloudWatch log inspection, never consumed by any caller."""
    today = datetime.now(UTC).date()
    with closing(SessionLocal()) as db:
        return generation.run(db, today=today)
