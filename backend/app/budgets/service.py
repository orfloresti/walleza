"""Business logic for the `budget-management` and `budget-progress`
capabilities (design D66-D78).

Every read/write here is built ONLY on top of
`app.budgets.queries.visible_budgets`/`budget_spent_totals` — this module
never resolves membership itself and never builds a competing query path
(mirrors `app.categories.service`'s exact structure). Referential
validation (category/account existence+visibility) reuses
`visible_categories`/`visible_accounts` directly, exactly as
`app.categories.service`'s `_validate_parent_reference` reuses
`visible_categories`.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.budgets.models import Budget
from app.budgets.queries import budget_spent_totals, visible_budgets
from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope


class BudgetNotFoundError(Exception):
    """Raised whenever a target budget id falls outside `visible_budgets`
    for the caller's scope — i.e. it belongs to a different workspace, or
    references an account the caller cannot see. Design D18's
    404-for-invisible-rows rule, reused exactly: a 403 would confirm the
    row exists at all."""


class BudgetValidationError(Exception):
    """Raised for a `category_id`/`account_id` that does not resolve
    inside the caller's workspace, or an account-scoped budget whose
    `currency` does not match its account's currency (design D73). Mapped
    to 422 by the router — never 404, because these are request BODY
    fields, not a resource being fetched by id."""


def _now() -> datetime:
    return datetime.now(UTC)


def _validate_category_reference(
    db: Session, *, scope: WorkspaceScope, category_id: uuid.UUID
) -> None:
    category = db.execute(
        visible_categories(scope).where(Category.id == category_id)
    ).scalar_one_or_none()
    if category is None:
        # Reject as if the reference did not exist — mirrors
        # app.categories.service._validate_parent_reference's exact
        # cross-workspace rejection pattern.
        raise BudgetValidationError("category not found")


def _validate_account_reference(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID, currency: str
) -> None:
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise BudgetValidationError("account not found")
    # Design D73: least surprise wins — a currency mismatch would
    # otherwise be a silent config error that permanently reports
    # spent=0 once progress computation lands (unit 1b).
    if account.currency != currency:
        raise BudgetValidationError(
            "budget currency must match the referenced account's currency"
        )


def list_budgets(db: Session, *, scope: WorkspaceScope) -> list[Budget]:
    query = visible_budgets(scope).order_by(Budget.created_at)
    return list(db.execute(query).scalars())


def get_budget(db: Session, *, scope: WorkspaceScope, budget_id: uuid.UUID) -> Budget:
    budget = db.execute(
        visible_budgets(scope).where(Budget.id == budget_id)
    ).scalar_one_or_none()
    if budget is None:
        raise BudgetNotFoundError("budget not found")
    return budget


def create_budget(
    db: Session,
    *,
    scope: WorkspaceScope,
    category_id: uuid.UUID,
    account_id: uuid.UUID | None,
    name: str | None,
    amount: Decimal,
    currency: str,
) -> Budget:
    _validate_category_reference(db, scope=scope, category_id=category_id)
    if account_id is not None:
        _validate_account_reference(
            db, scope=scope, account_id=account_id, currency=currency
        )

    now = _now()
    budget = Budget(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        category_id=category_id,
        account_id=account_id,
        name=name,
        amount=amount,
        currency=currency,
        created_at=now,
        updated_at=now,
    )
    db.add(budget)
    db.flush()
    return budget


def update_budget(
    db: Session,
    *,
    scope: WorkspaceScope,
    budget_id: uuid.UUID,
    changes: dict[str, object],
) -> Budget:
    """`changes` is the caller's already-`exclude_unset=True`-filtered
    patch body. Fetching through `get_budget` (i.e. through
    `visible_budgets`) means a PATCH aimed at a foreign workspace's budget
    404s before any write is attempted."""
    budget = get_budget(db, scope=scope, budget_id=budget_id)

    new_category_id = changes.get("category_id", budget.category_id)
    if "category_id" in changes:
        _validate_category_reference(db, scope=scope, category_id=new_category_id)

    new_account_id = changes.get("account_id", budget.account_id)
    new_currency = changes.get("currency", budget.currency)
    if new_account_id is not None and ("account_id" in changes or "currency" in changes):
        _validate_account_reference(
            db, scope=scope, account_id=new_account_id, currency=new_currency
        )

    for field, value in changes.items():
        setattr(budget, field, value)
    budget.updated_at = _now()
    db.flush()
    return budget


def delete_budget(db: Session, *, scope: WorkspaceScope, budget_id: uuid.UUID) -> None:
    budget = get_budget(db, scope=scope, budget_id=budget_id)
    db.delete(budget)
    db.flush()


# ---------------------------------------------------------------------------
# Progress computation (design D71-D78) — unit 1b.
# ---------------------------------------------------------------------------

# Design D75: one shared constant, never scattered across router/frontend.
# `on_track` below 80%, `near_limit` from 80% up to (but not including)
# 100%, `over_budget` at or above 100%. `percent` itself is reported
# unclamped (a 140%-over budget reports 140.0, not 100.0).
BUDGET_NEAR_LIMIT_THRESHOLD = Decimal("0.80")
BUDGET_OVER_BUDGET_THRESHOLD = Decimal("1.00")

BudgetStatus = str  # Literal["on_track", "near_limit", "over_budget"] — see schemas.py


def current_month_bounds(today: date) -> tuple[date, date]:
    """`(first day, last day)` of `today`'s calendar month, both inclusive
    (design D77). `visible_transactions` filters `date_to` with `<=`, so
    the last day returned here is correct to pass straight through
    without an off-by-one adjustment.

    Deliberately does NOT reuse `app.recurring`'s anchor-based `shift()` —
    that function tracks an anchor day across period boundaries for
    recurring generation, a different concern with no period enum and no
    drift to defend against here (design D77's explicit note)."""
    first_day = today.replace(day=1)
    _, days_in_month = calendar.monthrange(today.year, today.month)
    last_day = today.replace(day=days_in_month)
    return first_day, last_day


def classify_status(*, limit: Decimal, spent: Decimal) -> tuple[float, BudgetStatus]:
    """`(percent, status)` per design D75. `percent` is `spent / limit`,
    left unclamped; `limit` is always `> 0` (DB CHECK), so no
    divide-by-zero guard is needed."""
    ratio = spent / limit
    percent = float(ratio)
    if ratio >= BUDGET_OVER_BUDGET_THRESHOLD:
        status: BudgetStatus = "over_budget"
    elif ratio >= BUDGET_NEAR_LIMIT_THRESHOLD:
        status = "near_limit"
    else:
        status = "on_track"
    return percent, status


class BudgetProgress(NamedTuple):
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    percent: float
    status: BudgetStatus
    period_start: date
    period_end: date


def _progress_from_spent(budget: Budget, spent: Decimal, period: tuple[date, date]) -> BudgetProgress:
    percent, status = classify_status(limit=budget.amount, spent=spent)
    period_start, period_end = period
    return BudgetProgress(
        limit=budget.amount,
        spent=spent,
        remaining=budget.amount - spent,
        percent=percent,
        status=status,
        period_start=period_start,
        period_end=period_end,
    )


def get_budget_progress(
    db: Session, *, scope: WorkspaceScope, budget_id: uuid.UUID, today: date | None = None
) -> tuple[Budget, BudgetProgress]:
    """Single-budget read: fetches the budget (404 if invisible) and its
    current-month progress via the SAME grouped `budget_spent_totals`
    query the list endpoint uses (design D71/D72/D74), narrowed to one
    `budget_id` — not a hand-rolled second SUM expression."""
    budget = get_budget(db, scope=scope, budget_id=budget_id)
    period = current_month_bounds(today or datetime.now(UTC).date())
    period_start, period_end = period
    row = db.execute(
        budget_spent_totals(
            scope, period_start=period_start, period_end=period_end, budget_id=budget_id
        )
    ).one()
    return budget, _progress_from_spent(budget, Decimal(row.spent), period)


def list_budgets_with_progress(
    db: Session, *, scope: WorkspaceScope, today: date | None = None
) -> list[tuple[Budget, BudgetProgress]]:
    """List every visible budget with its current-month progress attached,
    computed via ONE grouped query (design D78) — never a per-budget SUM
    loop."""
    budgets = list_budgets(db, scope=scope)
    period = current_month_bounds(today or datetime.now(UTC).date())
    period_start, period_end = period
    spent_by_budget_id = {
        row.budget_id: Decimal(row.spent)
        for row in db.execute(
            budget_spent_totals(scope, period_start=period_start, period_end=period_end)
        )
    }
    return [
        (budget, _progress_from_spent(budget, spent_by_budget_id.get(budget.id, Decimal(0)), period))
        for budget in budgets
    ]
