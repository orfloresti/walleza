"""The `audit-log` capability (Phase 8 Unit 5, design D102-D105): an
append-only trail of privileged actions only — workspace-owner actions and
every platform-admin action — never ordinary CRUD (spec audit-log domain's
"Privileged-Action-Only Logging" requirement, product decision O2).

`record_audit()` (in `app/audit/service.py`) is called explicitly, inline,
by `app.workspace.service` and `app.admin.service`, sharing the caller's
own `Session` and never committing itself — the audit row commits or rolls
back with the mutation it documents (design D103's rationale for rejecting
middleware, which would run after commit).
"""

from __future__ import annotations
