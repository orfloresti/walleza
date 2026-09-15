"""The audit-log action catalog (design D103). Every member here MUST also
appear in migration `0011_audit_log.py`'s `ck_audit_log_action` CHECK
constraint — a typo'd action string is a DB error, not a silently
unqueryable row.

Deliberately excludes `workspace.member_left`: design D104's call-site
table originally paired it with `workspace/service.leave_workspace`, but
the confirmed spec (audit-log domain, "Self-Removal Is a Distinct Path"
and its "Self-removal not audited" scenario) requires self-removal to
produce NO audit row at all. Spec is the acceptance-criteria authority, so
this catalog — and `leave_workspace`'s call site — follow the spec, not
that one design table row. See apply-progress for the recorded deviation.
"""

from __future__ import annotations

from enum import StrEnum


class AuditAction(StrEnum):
    WORKSPACE_RENAMED = "workspace.renamed"
    WORKSPACE_MEMBER_REMOVED = "workspace.member_removed"
    WORKSPACE_INVITE_GENERATED = "workspace.invite_generated"
    WORKSPACE_INVITE_REVOKED = "workspace.invite_revoked"
    WORKSPACE_OWNERSHIP_TRANSFERRED = "workspace.ownership_transferred"
    PLATFORM_USER_DEACTIVATED = "platform.user_deactivated"
    PLATFORM_USER_REACTIVATED = "platform.user_reactivated"
    PLATFORM_WORKSPACE_DEACTIVATED = "platform.workspace_deactivated"
    PLATFORM_WORKSPACE_REACTIVATED = "platform.workspace_reactivated"
    PLATFORM_ADMIN_GRANTED = "platform.admin_granted"
    PLATFORM_ADMIN_REVOKED = "platform.admin_revoked"
    PLATFORM_ADMIN_SELF_REVOKED = "platform.admin_self_revoked"
