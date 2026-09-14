"""Business logic for the `report-category-breakdown` and
`report-default-currency` capabilities (design D79-D82, D86).

Every read is built ONLY on top of `app.reports.queries`'s scope-aware
selects — this module never resolves membership itself and never builds
a competing query path (mirrors `app.budgets.service`'s exact structure).
"""

from __future__ import annotations

import calendar
import datetime
import uuid
from decimal import Decimal
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope
from app.reports.queries import (
    category_breakdown_totals,
    default_currency_counts,
    trend_totals,
)

BUCKET_SIZES = ("day", "week", "month", "year")


class ReportValidationError(Exception):
    """Raised for an invalid date range (`date_from > date_to`) or an
    unrecognized `bucket` value. Mapped to 422 by the router."""


class TrendPoint(NamedTuple):
    """One densified trend bucket (design D84/D85)."""

    bucket_start: datetime.date
    bucket_end: datetime.date
    total: Decimal
    partial: bool


def _validate_currency(db: Session, *, scope: WorkspaceScope, currency: str) -> None:
    """Design D82: `currency` MUST match an ISO-4217 code used by at
    least one account visible in the workspace (spec's
    report-category-breakdown/report-trend domains) — a typo or an
    unused-but-syntactically-valid code must be REJECTED with a 422, not
    silently answered with an all-zero breakdown/trend. Reuses
    `visible_accounts` (never a new visibility predicate, mirrors
    `app.budgets.service._validate_account_reference`'s exact reasoning
    for reusing scope-aware queries rather than a fresh currency
    allowlist)."""
    matches = db.execute(
        sa.select(sa.literal(1))
        .select_from(visible_accounts(scope).where(Account.currency == currency).subquery())
        .limit(1)
    ).first()
    if matches is None:
        raise ReportValidationError(
            f"currency {currency!r} is not used by any account in this workspace"
        )


def roll_up(
    totals: dict[uuid.UUID, Decimal],
    parents: dict[uuid.UUID, uuid.UUID | None],
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Pure fold: `{category_id: (own, total)}`, `total = own + sum of
    direct children's own` (design D80).

    One pass over `totals`, adding each child's `own` into its parent's
    accumulator. Hierarchy depth is capped at 2 levels by the
    service-layer rule enforced elsewhere in the app (category creation);
    this fold ENFORCES that invariant rather than assuming it — it raises
    if it ever encounters a 3rd level (a category whose parent itself has
    a non-null parent), rather than silently under-reporting a
    grandparent's rollup.
    """
    zero = Decimal(0)
    own: dict[uuid.UUID, Decimal] = {
        category_id: totals.get(category_id, zero) for category_id in parents
    }
    total: dict[uuid.UUID, Decimal] = dict(own)

    for category_id, parent_id in parents.items():
        if parent_id is None:
            continue
        if parent_id not in parents:
            # A parent reference outside this scope's category set —
            # cannot happen given `Category.parent_id`'s RESTRICT FK and
            # `visible_categories`'s no-archived-branch guarantee (design
            # D82), but fail loudly rather than silently drop the child's
            # contribution if it ever did.
            raise ValueError(f"category {category_id} references an invisible parent")
        grandparent_id = parents[parent_id]
        if grandparent_id is not None:
            # `parent_id` is itself a child — a 3rd hierarchy level.
            # The 2-level cap is a service-layer rule elsewhere in the
            # app; this fold enforces it rather than under-reporting.
            raise ValueError(
                f"category {category_id} exceeds the 2-level hierarchy cap "
                f"(parent {parent_id} is itself a child)"
            )
        total[parent_id] = total[parent_id] + own[category_id]

    return {category_id: (own[category_id], total[category_id]) for category_id in parents}


def category_breakdown(
    db: Session,
    *,
    scope: WorkspaceScope,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str,
    type: str = "expense",
    account_id: uuid.UUID | None = None,
) -> list[tuple[Category, Decimal, Decimal]]:
    """Orchestrates D79's flat query + D80's rollup fold. Returns
    `(category, own, total)` for every visible category, one row per
    category — including zero-activity ones (design's "never omitted"
    requirement).

    `date_from > date_to` raises `ReportValidationError` (422 at the
    router) before any query runs.
    """
    if date_from > date_to:
        raise ReportValidationError("date_from must not be after date_to")
    _validate_currency(db, scope=scope, currency=currency)

    # ONE `visible_categories(scope)` fetch — no N+1 (proposal edge case
    # 7, mirrored from `app.budgets.service.list_budgets_with_progress`).
    categories = list(db.execute(visible_categories(scope)).scalars())
    parents = {category.id: category.parent_id for category in categories}
    by_id = {category.id: category for category in categories}

    totals = {
        row.category_id: Decimal(row.total)
        for row in db.execute(
            category_breakdown_totals(
                scope,
                date_from=date_from,
                date_to=date_to,
                currency=currency,
                type=type,
                account_id=account_id,
            )
        )
    }

    rolled = roll_up(totals, parents)
    return [
        (by_id[category_id], own, total) for category_id, (own, total) in rolled.items()
    ]


def resolve_bucket(bucket: str) -> str:
    """Validates `bucket` against `day|week|month|year` (design D88).
    Raises `ReportValidationError` (422 at the router) otherwise."""
    if bucket not in BUCKET_SIZES:
        raise ReportValidationError(
            f"bucket must be one of {BUCKET_SIZES!r}, got {bucket!r}"
        )
    return bucket


def bucket_bounds(d: datetime.date, bucket: str) -> tuple[datetime.date, datetime.date]:
    """Design D85: the calendar bucket `d` falls into, as `(start, end)`,
    both inclusive — matching `visible_transactions`'s inclusive `<=` on
    `date_to` (D85's own rationale).

    Uses only `datetime`/`calendar` stdlib arithmetic (no hand-rolled day
    counting), so DST transitions, leap years, and Dec->Jan rollovers are
    handled by the interpreter's own calendar rules rather than reimplemented
    here — dates carry no timezone/DST state at all (`datetime.date`, not
    `datetime.datetime`), so DST is a non-issue for this function; it is
    listed in the design/tasks as a boundary case to verify anyway.
    """
    if bucket == "day":
        return d, d
    if bucket == "week":
        # ISO Monday-aligned, matching Postgres `date_trunc('week', ...)`.
        start = d - datetime.timedelta(days=d.weekday())
        end = start + datetime.timedelta(days=6)
        return start, end
    if bucket == "month":
        start = d.replace(day=1)
        last_day = calendar.monthrange(d.year, d.month)[1]
        end = d.replace(day=last_day)
        return start, end
    if bucket == "year":
        return d.replace(month=1, day=1), d.replace(month=12, day=31)
    raise ReportValidationError(f"bucket must be one of {BUCKET_SIZES!r}, got {bucket!r}")


def _next_bucket_start(d: datetime.date, bucket: str) -> datetime.date:
    """The first date belonging to the NEXT calendar bucket after the one
    containing `d`. Built on `bucket_bounds` + `datetime.timedelta`, plus
    `calendar.monthrange` for month/year rollovers — never hand-rolled day
    arithmetic that reimplements what those already solve correctly across
    Dec->Jan and leap-year boundaries."""
    _, end = bucket_bounds(d, bucket)
    return end + datetime.timedelta(days=1)


def dense_series(
    rows: dict[datetime.date, Decimal],
    *,
    date_from: datetime.date,
    date_to: datetime.date,
    bucket: str,
) -> list[TrendPoint]:
    """Design D85: walks every calendar bucket from `date_from` through
    `date_to`, filling any bucket absent from `rows` with `Decimal("0")`
    — a pure Python fold, table-testable across DST, leap years, and
    Dec->Jan, with no gaps in the chart's x-domain.

    `rows` maps a bucket's `bucket_start` date to its (already
    range-clipped, per D84 — `visible_transactions` already filtered to
    `date_from..date_to`) total. A bucket partially overlapping the
    overall range at either edge is CLIPPED (already true of `rows`'
    sums), KEPT, and flagged `partial=True` (design D84).
    """
    if date_from > date_to:
        raise ReportValidationError("date_from must not be after date_to")

    points: list[TrendPoint] = []
    cursor = bucket_bounds(date_from, bucket)[0]
    zero = Decimal(0)

    while cursor <= date_to:
        start, end = bucket_bounds(cursor, bucket)
        partial = start < date_from or end > date_to
        points.append(
            TrendPoint(
                bucket_start=start,
                bucket_end=end,
                total=rows.get(start, zero),
                partial=partial,
            )
        )
        cursor = _next_bucket_start(cursor, bucket)

    return points


def trend(
    db: Session,
    *,
    scope: WorkspaceScope,
    date_from: datetime.date,
    date_to: datetime.date,
    currency: str,
    bucket: str,
    type: str = "expense",
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
) -> list[TrendPoint]:
    """Orchestrates D83's bucketed SQL query + D85's Python densification.
    `date_from > date_to` or an unrecognized `bucket` raises
    `ReportValidationError` (422 at the router) before any query runs."""
    if date_from > date_to:
        raise ReportValidationError("date_from must not be after date_to")
    _validate_currency(db, scope=scope, currency=currency)
    bucket = resolve_bucket(bucket)

    rows = {
        row.bucket_start.date()
        if isinstance(row.bucket_start, datetime.datetime)
        else row.bucket_start: Decimal(row.total)
        for row in db.execute(
            trend_totals(
                scope,
                date_from=date_from,
                date_to=date_to,
                currency=currency,
                bucket=bucket,
                type=type,
                account_id=account_id,
                category_id=category_id,
            )
        )
    }

    return dense_series(rows, date_from=date_from, date_to=date_to, bucket=bucket)


def default_currency(db: Session, *, scope: WorkspaceScope) -> str | None:
    """Design D86: most-used currency by transaction count, tie-broken by
    the earliest-created account, then `currency` ASC. Returns `None` for
    a workspace with zero accounts — the frontend then prompts for an
    explicit currency selection rather than showing a blank selector."""
    row = db.execute(default_currency_counts(scope)).first()
    if row is None:
        return None
    return row.currency
