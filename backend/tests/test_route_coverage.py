"""RED -> GREEN: every route mounted under `/api/workspace`, `/api/accounts`,
`/api/categories`, or `/api/transactions` (including its
`/api/transactions/{id}/photo/...` attachment sub-routes) must resolve
`app.deps.require_membership` somewhere in its dependant tree (design
D14's second structural layer) — the single, deliberately allow-listed
exception being `GET /api/workspace` itself (design D13: get-or-create
must run BEFORE any membership row is guaranteed to exist, so that one
route intentionally depends only on `get_current_user`).

A future endpoint that forgets `Depends(require_membership)`, or is
mounted on the wrong router, fails THIS test — not a manual security
review (spec RED #9, tasks.md task 2.3). This test walks whatever
`create_app()` actually registers via `fastapi.routing.iter_route_contexts`
(the same resolution `FastAPI.openapi()` itself uses internally, so it
sees the FULLY MERGED, include-time dependant — router-level
`dependencies=[Depends(require_membership)]` included — not just each
route's own locally-declared dependencies), so it keeps proving the same
guarantee for any future router with no changes needed here beyond
extending the path-prefix tuple below.

`/api/categories` and `/api/transactions` were added to the prefix tuple
here in PR5 (tasks.md task 6.10) — they were deliberately NOT added when
PR2/PR3 introduced those routers (see `sdd/phase-2-categories-
transactions/apply-progress`'s PR2 section for the confirmed, explicitly
carried-forward gap this closes): every categories/transactions route WAS
already gated by `require_membership` all along, and was already proven
so end-to-end by `tests/categories/test_category_visibility.py` and
`tests/transactions/test_transaction_visibility.py`; this structural
meta-test simply did not walk those prefixes yet.

`/api/transfers` was added to the prefix tuple here in Phase 3 PR1
(tasks.md task 1.21, design RED #17) — with NO modification to this
test's assertion logic, mirroring PR5's exact pattern above: it confirms
the new `app.transfers.router` is fully gated by `require_membership`
just like every other router on this list.

`/api/templates` and `/api/recurring` were added to the prefix tuple here
in Phase 4 PR1 (tasks.md task 1.19), same pattern once more: both new
routers are fully gated by `require_membership` — no application-level
generation route is registered anywhere (occurrence generation, a later
PR, has no REST contract at all per design).

`/api/budgets` was added to the prefix tuple here in Phase 5 PR1a
(tasks.md task 1a.6), same pattern once more: the new `app.budgets.router`
is fully gated by `require_membership` just like every other router on
this list.

`/api/reports` was added to the prefix tuple here in Phase 8 PR0 (design
D108, tasks.md Unit 0 task 0.1), closing a previously-live gap: the
`app.reports.router` was already fully gated by `require_membership` in
the actual route code, but this structural test never walked its prefix,
so a future regression there would not have been caught. No change to
the actual route code was needed — only to this test's coverage.

Phase 8 Unit 2 (design D108) adds a SECOND governed tuple,
`_PLATFORM_ADMIN_PREFIXES`, with the INVERSE assertion: every route under
`/api/admin` must resolve `require_platform_admin` and must NOT resolve
`require_membership` — the two authority paths must never overlap on a
single route (mirrors design D99's "no dual-context function" guarantee,
one level up at the routing layer). This Unit ships no `/api/admin`
route yet (see `app/admin/__init__.py`), so
`test_every_admin_route_requires_platform_admin_only` currently proves
the assertion vacuously true over zero routes; it starts enforcing for
real the moment Unit 3 registers `app.admin.router`.

`test_every_api_route_is_governed_exactly_once` (task 2.9) is the
totality test: every registered `/api/` route must fall under exactly
one of the two governed tuples above, or the explicit, UNCHANGED
`_ALLOWLISTED_UNGATED_ROUTES` set — so a future router mounted under an
unlisted prefix fails the build instead of silently escaping both
guarantees.
"""

from __future__ import annotations

from fastapi import routing
from fastapi.dependencies.models import Dependant

from app.admin.deps import require_platform_admin
from app.deps import require_membership
from app.main import create_app

# (path, HTTP method) pairs deliberately exempt from the membership gate,
# each with the design decision that justifies the exemption. NO new
# entries were added in Phase 8 (design D108's totality requirement,
# "Allowlist unchanged" scenario) — `/api/auth/*`, `/api/me`, and
# `/api/health` are already-ungated-today routes, enumerated explicitly
# below only so the totality test can account for them, not as new
# carve-outs.
_ALLOWLISTED_UNGATED_ROUTES: set[tuple[str, str]] = {
    ("/api/workspace", "GET"),  # design D13: get-or-create precedes membership
}

_MEMBERSHIP_GOVERNED_PREFIXES: tuple[str, ...] = (
    "/api/workspace",
    "/api/accounts",
    "/api/categories",
    "/api/transactions",
    "/api/transfers",
    "/api/templates",
    "/api/recurring",
    "/api/budgets",
    "/api/reports",
)

_PLATFORM_ADMIN_PREFIXES: tuple[str, ...] = ("/api/admin",)

# Pre-existing-and-named ungated prefixes (design D108's "Allowlist
# unchanged" scenario): `/api/auth/*` and `/api/me` are authentication
# itself (nothing to gate against yet), `/api/health` is a liveness
# probe. None of these is new to this phase.
_UNGATED_PREFIXES: tuple[str, ...] = ("/api/auth", "/api/me", "/api/health")


def _dependency_closure(dependant: Dependant) -> set[object]:
    """All callables reachable from `dependant`, including its own
    sub-dependencies (`Depends(...)` of `Depends(...)`), so a dependency
    that itself depends on `require_membership` (rather than depending on
    it directly) is still detected."""
    seen: set[object] = set()
    stack = [dependant]
    while stack:
        current = stack.pop()
        if current.call is not None:
            seen.add(current.call)
        stack.extend(current.dependencies)
    return seen


def test_every_workspace_and_accounts_route_requires_membership_except_bootstrap() -> None:
    app = create_app()
    checked = 0

    for route_context in routing.iter_route_contexts(app.routes):
        path = route_context.path
        methods = route_context.methods
        if not path or not methods:
            continue
        if not path.startswith(_MEMBERSHIP_GOVERNED_PREFIXES):
            continue

        for method in methods - {"HEAD", "OPTIONS"}:
            checked += 1
            if (path, method) in _ALLOWLISTED_UNGATED_ROUTES:
                continue

            dependant = route_context.dependant
            assert dependant is not None, f"{method} {path} resolved no dependant at all"
            dependencies = _dependency_closure(dependant)
            assert require_membership in dependencies, (
                f"{method} {path} does not resolve require_membership "
                "anywhere in its dependency tree"
            )

    assert checked > 0, "no workspace/accounts routes were found to check"


def test_every_admin_route_requires_platform_admin_only() -> None:
    """Design D108's INVERSE assertion: every `/api/admin/*` route must
    resolve `require_platform_admin` and must NOT resolve
    `require_membership`. This Unit ships no `/api/admin` route yet, so
    `checked` may legitimately be 0 here — the assertion still runs and
    will start rejecting a wrongly-gated route the moment Unit 3 adds
    one."""
    app = create_app()

    for route_context in routing.iter_route_contexts(app.routes):
        path = route_context.path
        methods = route_context.methods
        if not path or not methods:
            continue
        if not path.startswith(_PLATFORM_ADMIN_PREFIXES):
            continue

        for method in methods - {"HEAD", "OPTIONS"}:
            dependant = route_context.dependant
            assert dependant is not None, f"{method} {path} resolved no dependant at all"
            dependencies = _dependency_closure(dependant)
            assert require_platform_admin in dependencies, (
                f"{method} {path} does not resolve require_platform_admin "
                "anywhere in its dependency tree"
            )
            assert require_membership not in dependencies, (
                f"{method} {path} resolves require_membership — an "
                "/api/admin route must be governed by require_platform_admin "
                "ONLY (design D108)"
            )


def test_every_api_route_is_governed_exactly_once() -> None:
    """Design D108's totality test (task 2.9): every registered `/api/`
    route must fall under exactly one of the two governed prefix tuples,
    or the explicit, unchanged `_ALLOWLISTED_UNGATED_ROUTES` set / the
    named pre-existing ungated prefixes — never both, never neither."""
    app = create_app()
    checked = 0

    for route_context in routing.iter_route_contexts(app.routes):
        path = route_context.path
        methods = route_context.methods
        if not path or not methods or not path.startswith("/api/"):
            continue

        is_membership_prefixed = path.startswith(_MEMBERSHIP_GOVERNED_PREFIXES)
        is_admin_prefixed = path.startswith(_PLATFORM_ADMIN_PREFIXES)
        is_named_ungated_prefix = path.startswith(_UNGATED_PREFIXES)

        assert not (is_membership_prefixed and is_admin_prefixed), (
            f"{path} matches BOTH the membership and admin governed prefixes"
        )

        for method in methods - {"HEAD", "OPTIONS"}:
            checked += 1
            is_allowlisted_route = (path, method) in _ALLOWLISTED_UNGATED_ROUTES

            governed = is_membership_prefixed or is_admin_prefixed
            ungated = is_named_ungated_prefix or is_allowlisted_route

            assert governed or ungated, (
                f"{method} {path} falls under neither governed prefix tuple "
                "nor the ungated allowlist — a new router must be added to "
                "one of them (design D108 totality)"
            )

    assert checked > 0, "no /api/ routes were found to check"
