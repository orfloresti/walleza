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
"""

from __future__ import annotations

from fastapi import routing
from fastapi.dependencies.models import Dependant

from app.deps import require_membership
from app.main import create_app

# (path, HTTP method) pairs deliberately exempt from the membership gate,
# each with the design decision that justifies the exemption.
_ALLOWLISTED_UNGATED_ROUTES: set[tuple[str, str]] = {
    ("/api/workspace", "GET"),  # design D13: get-or-create precedes membership
}


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
        if not path.startswith(
            (
                "/api/workspace",
                "/api/accounts",
                "/api/categories",
                "/api/transactions",
                "/api/transfers",
                "/api/templates",
                "/api/recurring",
            )
        ):
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
