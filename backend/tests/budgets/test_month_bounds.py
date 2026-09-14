"""Table-driven unit tests for `current_month_bounds` (design D77,
tasks.md 1b.1). Pure function, no DB required.
"""

from __future__ import annotations

import datetime

import pytest

from app.budgets.service import current_month_bounds


@pytest.mark.parametrize(
    ("today", "expected_start", "expected_end"),
    [
        # Plain January.
        (datetime.date(2026, 1, 15), datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),
        # Non-leap February.
        (datetime.date(2026, 2, 1), datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)),
        # Leap-year February.
        (datetime.date(2028, 2, 29), datetime.date(2028, 2, 1), datetime.date(2028, 2, 29)),
        # December — year-boundary month, must not roll into next January.
        (datetime.date(2026, 12, 31), datetime.date(2026, 12, 1), datetime.date(2026, 12, 31)),
        # Mid-month creation still yields the FULL month (design D76 —
        # the helper itself has no notion of "since creation").
        (datetime.date(2026, 6, 20), datetime.date(2026, 6, 1), datetime.date(2026, 6, 30)),
    ],
)
def test_current_month_bounds(
    today: datetime.date, expected_start: datetime.date, expected_end: datetime.date
) -> None:
    assert current_month_bounds(today) == (expected_start, expected_end)
