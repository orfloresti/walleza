"""RED -> GREEN, design D85, tasks.md 2.13: exhaustive pure-function
coverage for `bucket_bounds`/`dense_series` — no DB, table-driven, across
DST transitions, leap-year February, Dec->Jan boundaries, single-bucket
ranges, and partial edge buckets.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from app.reports.service import ReportValidationError, bucket_bounds, dense_series

# --- bucket_bounds --------------------------------------------------------


def test_bucket_bounds_day_is_itself() -> None:
    d = datetime.date(2026, 3, 15)
    assert bucket_bounds(d, "day") == (d, d)


def test_bucket_bounds_week_aligns_to_iso_monday() -> None:
    # 2026-03-18 is a Wednesday.
    d = datetime.date(2026, 3, 18)
    start, end = bucket_bounds(d, "week")
    assert start == datetime.date(2026, 3, 16)  # Monday
    assert end == datetime.date(2026, 3, 22)  # Sunday
    assert start.weekday() == 0


def test_bucket_bounds_month_leap_february() -> None:
    d = datetime.date(2028, 2, 10)  # 2028 is a leap year
    start, end = bucket_bounds(d, "month")
    assert start == datetime.date(2028, 2, 1)
    assert end == datetime.date(2028, 2, 29)


def test_bucket_bounds_month_non_leap_february() -> None:
    d = datetime.date(2027, 2, 10)
    start, end = bucket_bounds(d, "month")
    assert start == datetime.date(2027, 2, 1)
    assert end == datetime.date(2027, 2, 28)


def test_bucket_bounds_year() -> None:
    d = datetime.date(2026, 7, 4)
    start, end = bucket_bounds(d, "year")
    assert start == datetime.date(2026, 1, 1)
    assert end == datetime.date(2026, 12, 31)


def test_bucket_bounds_invalid_bucket_raises() -> None:
    with pytest.raises(ReportValidationError):
        bucket_bounds(datetime.date(2026, 1, 1), "fortnight")


# --- dense_series -----------------------------------------------------------


def test_dense_series_fills_middle_gap_with_zero() -> None:
    date_from = datetime.date(2026, 1, 1)
    date_to = datetime.date(2026, 1, 3)
    rows = {
        datetime.date(2026, 1, 1): Decimal("10.00"),
        datetime.date(2026, 1, 3): Decimal("5.00"),
    }
    points = dense_series(rows, date_from=date_from, date_to=date_to, bucket="day")

    assert [p.bucket_start for p in points] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 2),
        datetime.date(2026, 1, 3),
    ]
    assert points[1].total == Decimal(0)
    assert all(not p.partial for p in points)


def test_dense_series_month_dec_to_jan_boundary() -> None:
    date_from = datetime.date(2025, 12, 15)
    date_to = datetime.date(2026, 1, 15)
    points = dense_series({}, date_from=date_from, date_to=date_to, bucket="month")

    assert [p.bucket_start for p in points] == [
        datetime.date(2025, 12, 1),
        datetime.date(2026, 1, 1),
    ]
    # Both edge buckets are partial: Dec bucket starts before date_from's
    # month wouldn't apply here since date_from is mid-December — but the
    # bucket itself (Dec 1-31) starts before date_from (Dec 15).
    assert points[0].partial is True
    # Jan bucket (Jan 1-31) ends after date_to (Jan 15).
    assert points[1].partial is True


def test_dense_series_leap_year_february_daily() -> None:
    date_from = datetime.date(2028, 2, 27)
    date_to = datetime.date(2028, 3, 1)
    points = dense_series({}, date_from=date_from, date_to=date_to, bucket="day")

    assert [p.bucket_start for p in points] == [
        datetime.date(2028, 2, 27),
        datetime.date(2028, 2, 28),
        datetime.date(2028, 2, 29),
        datetime.date(2028, 3, 1),
    ]


def test_dense_series_dst_transition_range_daily() -> None:
    # US DST spring-forward 2026-03-08; `datetime.date` carries no tz/DST
    # state at all, so this is a plain calendar-day walk — verifying that
    # explicitly since DST is called out as a boundary case in design/tasks.
    date_from = datetime.date(2026, 3, 7)
    date_to = datetime.date(2026, 3, 9)
    points = dense_series({}, date_from=date_from, date_to=date_to, bucket="day")

    assert [p.bucket_start for p in points] == [
        datetime.date(2026, 3, 7),
        datetime.date(2026, 3, 8),
        datetime.date(2026, 3, 9),
    ]
    assert len(points) == 3


def test_dense_series_single_bucket_range() -> None:
    d = datetime.date(2026, 6, 15)
    points = dense_series(
        {d: Decimal("42.00")}, date_from=d, date_to=d, bucket="day"
    )
    assert len(points) == 1
    assert points[0].total == Decimal("42.00")
    assert points[0].partial is False


def test_dense_series_partial_edge_buckets_week() -> None:
    # Range starts mid-week (Wednesday) and ends mid-week (Thursday).
    date_from = datetime.date(2026, 3, 18)  # Wednesday
    date_to = datetime.date(2026, 3, 26)  # Thursday, next week
    points = dense_series({}, date_from=date_from, date_to=date_to, bucket="week")

    assert len(points) == 2
    first, second = points
    assert first.bucket_start == datetime.date(2026, 3, 16)  # Monday before range
    assert first.partial is True  # bucket starts before date_from
    assert second.bucket_end == datetime.date(2026, 3, 29)  # Sunday after range
    assert second.partial is True  # bucket ends after date_to


def test_dense_series_year_bucket_multi_year_range() -> None:
    date_from = datetime.date(2025, 6, 1)
    date_to = datetime.date(2027, 3, 1)
    points = dense_series({}, date_from=date_from, date_to=date_to, bucket="year")

    assert [p.bucket_start.year for p in points] == [2025, 2026, 2027]
    assert points[0].partial is True
    assert points[1].partial is False
    assert points[2].partial is True


def test_dense_series_invalid_range_raises() -> None:
    with pytest.raises(ReportValidationError):
        dense_series(
            {},
            date_from=datetime.date(2026, 1, 5),
            date_to=datetime.date(2026, 1, 1),
            bucket="day",
        )
