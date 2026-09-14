"""Business logic for the `report-category-breakdown` and
`report-default-currency` capabilities (design D79-D82, D86).

Every read is built ONLY on top of `app.reports.queries`'s scope-aware
selects — this module never resolves membership itself and never builds
a competing query path (mirrors `app.budgets.service`'s exact structure).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope
from app.reports.queries import category_breakdown_totals, default_currency_counts


class ReportValidationError(Exception):
    """Raised for an invalid date range (`date_from > date_to`). Mapped to
    422 by the router."""


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


def default_currency(db: Session, *, scope: WorkspaceScope) -> str | None:
    """Design D86: most-used currency by transaction count, tie-broken by
    the earliest-created account, then `currency` ASC. Returns `None` for
    a workspace with zero accounts — the frontend then prompts for an
    explicit currency selection rather than showing a blank selector."""
    row = db.execute(default_currency_counts(scope)).first()
    if row is None:
        return None
    return row.currency
