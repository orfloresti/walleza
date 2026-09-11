"""The `recurring-reminders` capability's email-sending surface (design
D52-D54). Sibling of `app/storage.py`/`app/deps.py`/`app/security.py` — the
only place `sesv2` (SESv2) is ever touched in application code.

Deliberately never imported by `app.main` (design's re-derived threat case
7): the only principal in the account holding `ses:SendEmail` is the
scheduler execution role (`infra/ses.tf`'s `scheduler_ses` policy, attached
to `aws_iam_role.scheduler_exec` — never `aws_iam_role.lambda_exec`), so the
public HTTP Lambda must never even import this package, let alone call it.
"""

from __future__ import annotations
