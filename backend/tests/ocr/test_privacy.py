"""Design D117's privacy rule, tasks.md Unit 5 (task 5.7): `raw_response`
contains real receipt contents and must never be logged, fixtured, or
goldened. Structural AST scan, mirroring the existing audit-privacy test
precedent (design D103) — no `logger.*(...)` call anywhere under
`app/ocr/` (nor `app/ocr_worker.py`) may pass an argument or keyword
whose name contains `raw_response` or starts with `extracted_`.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OCR_PACKAGE_DIR = BACKEND_DIR / "app" / "ocr"
OCR_WORKER_FILE = BACKEND_DIR / "app" / "ocr_worker.py"

_FORBIDDEN_NAME_FRAGMENTS = ("raw_response", "extracted_")


def _is_logger_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and (func.value.id in {"logger", "logging"})
    )


def _flags_forbidden_name(name: str) -> bool:
    lowered = name.lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_NAME_FRAGMENTS)


def _scan_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_logger_call(node):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name) and _flags_forbidden_name(arg.id):
                violations.append(f"{path}:{node.lineno} positional arg `{arg.id}`")
        for keyword in node.keywords:
            if keyword.arg and _flags_forbidden_name(keyword.arg):
                violations.append(f"{path}:{node.lineno} keyword `{keyword.arg}`")
    return violations


def test_no_logger_call_under_app_ocr_takes_raw_response_or_extracted_fields() -> None:
    violations: list[str] = []
    files = list(OCR_PACKAGE_DIR.rglob("*.py"))
    if OCR_WORKER_FILE.exists():
        files.append(OCR_WORKER_FILE)
    for path in files:
        violations.extend(_scan_file(path))
    assert violations == [], f"privacy-sensitive logger call(s) found: {violations}"
