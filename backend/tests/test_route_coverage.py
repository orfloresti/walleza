"""RED -> GREEN: every route mounted under `/api/workspace` or
`/api/accounts` must resolve `app.deps.require_membership` somewhere in
its dependant tree (design D14's second structural layer) — the single,
deliberately allow-listed exception being `GET /api/workspace` itself
(design D13: get-or-create must run BEFORE any membership row is
guaranteed to exist, so that one route intentionally depends only on
`get_current_user`).

A future endpoint that forgets `Depends(require_membership)`, or is
mounted on the wrong router, fails THIS test — not a manual security
review (spec RED #9, tasks.md task 2.3). `/api/accounts` routes do not
exist yet in this PR (accounts CRUD is PR3); this test walks whatever
`create_app()` actually registers via `fastapi.routing.iter_route_contexts`
(the same resolution `FastAPI.openapi()` itself uses internally, so it
sees the FULLY MERGED, include-time dependant — router-level
`dependencies=[Depends(require_membership)]` included — not just each
route's own locally-declared dependencies), so it keeps proving the same
guarantee once PR3 adds accounts routes, with no changes needed here.
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
        if not path.startswith(("/api/workspace", "/api/accounts")):
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
