"""Platform-admin authority package (Phase 8 Unit 2, design D97-D100).

This package is deliberately a SEPARATE, PARALLEL authority surface next
to `app.deps.WorkspaceScope`/`require_membership` — never an extension of
it. Two structural guarantees are enforced by tests, not by review
discipline alone:

- `backend/tests/admin/test_authority_isolation.py` proves
  `PlatformAdminContext` (this package) and `WorkspaceScope`
  (`app.deps`) are never convertible into each other and never both
  accepted by the same callable (design D99).
- The same test module's import-firewall check proves this package never
  imports from any financial-domain module — `app.transactions`,
  `app.budgets`, `app.categories`, `app.transfers`, `app.templates`,
  `app.recurring`, `app.reports`, `app.accounts` — at module level OR
  function level (design D100).

This Unit ships ONLY the authority boundary: the `platform_admin` table
(migration `0008`), `PlatformAdminContext`/`require_platform_admin`
(`app.admin.deps`), the bootstrap entrypoint (`app.admin.bootstrap`), and
the two structural tests above. No admin capability route exists yet —
that is Phase 8 Unit 3, built strictly on top of this already-reviewed
boundary.
"""

from __future__ import annotations
