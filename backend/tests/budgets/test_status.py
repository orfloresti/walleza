"""Table-driven unit tests for `classify_status` (design D75, tasks.md
1b.2). Pure function, no DB required.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.budgets.service import classify_status


@pytest.mark.parametrize(
    ("spent", "limit", "expected_status"),
    [
        (Decimal("399.99"), Decimal("500.00"), "on_track"),  # 79.998%
        (Decimal("400.00"), Decimal("500.00"), "near_limit"),  # exactly 80%
        (Decimal("499.99"), Decimal("500.00"), "near_limit"),  # 99.998%
        (Decimal("500.00"), Decimal("500.00"), "over_budget"),  # exactly 100%
        (Decimal("700.00"), Decimal("500.00"), "over_budget"),  # 140%
    ],
)
def test_classify_status_thresholds(
    spent: Decimal, limit: Decimal, expected_status: str
) -> None:
    percent, status = classify_status(limit=limit, spent=spent)
    assert status == expected_status
    assert percent == pytest.approx(float(spent / limit))


def test_classify_status_percent_is_unclamped_over_100() -> None:
    percent, status = classify_status(limit=Decimal("500.00"), spent=Decimal("700.00"))
    assert status == "over_budget"
    assert percent == pytest.approx(1.4)
