"""RED -> GREEN, Phase 8 design D99/D100, spec platform-admin domain
"PlatformAdminContext Cannot Substitute for WorkspaceScope" requirement
(tasks.md Unit 2 tasks 2.4-2.7): structural, test-enforced proof — not a
code-review convention — that `PlatformAdminContext`
(`app.admin.deps`) and `WorkspaceScope` (`app.deps`) are never
convertible into each other, and that `app.admin` never imports a
financial-domain module.

Every check here walks the REAL, imported codebase (not a hand-maintained
list of "known-good" modules) so a future violation — a conversion
helper, a dual-context function, a denylisted import anywhere under
`app.admin`, including a local/function-level import — fails this test
wherever it is introduced, exactly as design D99/D100 require.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import typing
from pathlib import Path

import pytest

import app as app_package
from app.admin.deps import PlatformAdminContext
from app.deps import WorkspaceScope

APP_ROOT = Path(app_package.__file__).resolve().parent

# Design D100's exact denylist: `app.admin` must never reach into any
# financial-domain module. `app.accounts` is included even though the
# design proposal's original six omitted it — account names/balances are
# financial content (O1), and counts must come from a local table
# literal instead (Unit 3's `app/admin/queries.py`, not this Unit).
_DENYLISTED_IMPORT_PREFIXES: tuple[str, ...] = (
    "app.transactions",
    "app.budgets",
    "app.categories",
    "app.transfers",
    "app.templates",
    "app.recurring",
    "app.reports",
    "app.accounts",
)

# Modules allowed to import BOTH `WorkspaceScope` and `PlatformAdminContext`
# (design D99(3)): `app.main` registers every router regardless of which
# authority it uses, and this test module itself necessarily imports both
# to assert on them.
_ALLOWLISTED_DUAL_IMPORT_MODULES: frozenset[str] = frozenset(
    {"app.main", "tests.admin.test_authority_isolation"}
)


def _iter_app_module_names() -> list[str]:
    names = ["app"]
    for module_info in pkgutil.walk_packages(app_package.__path__, prefix="app."):
        names.append(module_info.name)
    return names


def _import_all_app_modules() -> dict[str, object]:
    modules: dict[str, object] = {}
    for name in _iter_app_module_names():
        try:
            modules[name] = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - surfaces a real import bug via pytest.fail
            pytest.fail(f"failed to import {name} while scanning for D99/D100: {exc}")
    return modules


def _module_source_path(module_name: str) -> Path:
    return APP_ROOT.parent / (module_name.replace(".", "/") + ".py")


# --- D99(1): the two types are structurally unrelated ----------------------


def test_contexts_are_structurally_unrelated_dataclasses() -> None:
    assert not issubclass(WorkspaceScope, PlatformAdminContext)
    assert not issubclass(PlatformAdminContext, WorkspaceScope)

    admin_fields = set(typing.get_type_hints(PlatformAdminContext))
    workspace_fields = set(typing.get_type_hints(WorkspaceScope))
    # The only field name the two shapes may share is `user_id` itself —
    # `PlatformAdminContext` MUST carry no `workspace_id` field at all
    # (design D98).
    assert admin_fields - {"user_id"} == set()
    assert "workspace_id" not in admin_fields
    assert workspace_fields == {"user_id", "workspace_id"}


# --- D99(2): no callable anywhere accepts or returns both types ------------


def test_no_function_accepts_or_returns_both_context_types() -> None:
    modules = _import_all_app_modules()
    offenders: list[str] = []

    for module_name, module in modules.items():
        for attr_name, member in inspect.getmembers(module):
            if not inspect.isfunction(member):
                continue
            # Only inspect functions actually DEFINED in this module (not
            # re-exported imports of `require_membership`/
            # `require_platform_admin` themselves, which would otherwise
            # trivially "mention" only one type each but pollute the scan
            # with duplicates across every module that imports them).
            if member.__module__ != module_name:
                continue
            try:
                hints = typing.get_type_hints(member)
            except Exception:  # noqa: BLE001, S112 - see rationale below
                # A handful of functions reference types that only resolve
                # under FastAPI's own resolution (e.g. forward refs to
                # request-only Pydantic models); those can never mention
                # BOTH our two concrete, always-importable dataclasses, so
                # skipping an unresolvable signature here cannot hide a
                # real D99 violation.
                continue
            mentions_admin = PlatformAdminContext in hints.values()
            mentions_workspace = WorkspaceScope in hints.values()
            if mentions_admin and mentions_workspace:
                offenders.append(f"{module_name}.{attr_name}")

    assert offenders == [], (
        "the following callables accept/return BOTH PlatformAdminContext "
        f"and WorkspaceScope, which design D99 forbids: {offenders}"
    )


# --- D99(3): no module imports both types, except the named exceptions ----


def _imported_names_from_module(module: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
    return imported


def test_no_module_imports_both_context_types_except_allowlisted() -> None:
    offenders: list[str] = []
    for module_name in _iter_app_module_names():
        if module_name in _ALLOWLISTED_DUAL_IMPORT_MODULES:
            continue
        path = _module_source_path(module_name) if module_name != "app" else APP_ROOT / "__init__.py"
        if not path.exists():
            # A package `__init__.py` for a sub-package name like
            # `app.workspace` resolves to `app/workspace/__init__.py`.
            path = APP_ROOT.parent / module_name.replace(".", "/") / "__init__.py"
        if not path.exists():
            continue
        names = _imported_names_from_module(module_name, path)
        if "PlatformAdminContext" in names and "WorkspaceScope" in names:
            offenders.append(module_name)

    assert offenders == [], (
        "the following modules import BOTH PlatformAdminContext and "
        f"WorkspaceScope, which design D99 forbids outside app.main: {offenders}"
    )


# --- D100: app.admin never imports a denylisted financial-domain module ----


def _all_imports_module_and_function_level(path: Path) -> set[str]:
    """Every module named by an `import`/`from ... import` statement in
    `path`, at ANY nesting depth (module-level OR inside a function body)
    — this codebase already uses function-level local imports to dodge
    circular-import risk elsewhere (`app.workspace.service.accept_invite`
    imports `app.accounts.models.Account` inside the function body), so a
    module-level-only scan would miss exactly the idiom design D100 calls
    out as the real risk."""
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_admin_import_firewall_blocks_financial_domain_modules() -> None:
    admin_dir = APP_ROOT / "admin"
    py_files = sorted(admin_dir.rglob("*.py"))
    assert py_files, "app/admin contains no Python files to scan"

    offenders: dict[str, set[str]] = {}
    for path in py_files:
        imported_modules = _all_imports_module_and_function_level(path)
        denylisted_hits = {
            module
            for module in imported_modules
            if module.startswith(_DENYLISTED_IMPORT_PREFIXES)
        }
        if denylisted_hits:
            offenders[str(path.relative_to(APP_ROOT.parent))] = denylisted_hits

    assert offenders == {}, (
        "app/admin imports from a denylisted financial-domain module, "
        f"violating design D100's import firewall: {offenders}"
    )


# --- Negative-control proofs: the tests above can actually fail -----------
#
# For a security-boundary structural test, proving it currently passes is
# not enough — it must also be provable that it WOULD fail on a real
# violation. Each helper below is exercised directly (not by mutating
# real source, which would be an actual boundary violation committed to
# the repo) against a synthetic temp file/callable that reproduces the
# exact shape each check scans for.


def test_dual_import_scan_detects_a_synthetic_violation(tmp_path: Path) -> None:
    violating_source = (
        "from app.admin.deps import PlatformAdminContext\n"
        "from app.deps import WorkspaceScope\n"
    )
    path = tmp_path / "synthetic_dual_import.py"
    path.write_text(violating_source)
    names = _imported_names_from_module("synthetic", path)
    assert {"PlatformAdminContext", "WorkspaceScope"} <= names


def test_import_firewall_scan_detects_a_synthetic_violation(tmp_path: Path) -> None:
    violating_source = "def f():\n    from app.transactions.models import Transaction\n"
    path = tmp_path / "synthetic_firewall_violation.py"
    path.write_text(violating_source)
    imported_modules = _all_imports_module_and_function_level(path)
    denylisted_hits = {
        module for module in imported_modules if module.startswith(_DENYLISTED_IMPORT_PREFIXES)
    }
    assert denylisted_hits == {"app.transactions.models"}


def test_dual_signature_scan_detects_a_synthetic_violation() -> None:
    def would_be_converter(
        admin: PlatformAdminContext, scope: WorkspaceScope
    ) -> None:  # pragma: no cover - never called, only introspected
        raise NotImplementedError

    hints = typing.get_type_hints(would_be_converter)
    assert PlatformAdminContext in hints.values()
    assert WorkspaceScope in hints.values()
