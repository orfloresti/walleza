"""Business logic for the `budget-management` capability (design D66-D70,
D73). CRUD portion only (unit 1a) — progress computation (D71-D78) is
unit 1b's responsibility and lands in this same module later.

Every read/write here is built ONLY on top of
`app.budgets.queries.visible_budgets` — this module never resolves
membership itself and never builds a competing query path (mirrors
`app.categories.service`'s exact structure). Referential validation
(category/account existence+visibility) reuses `visible_categories`/
`visible_accounts` directly, exactly as `app.categories.service`'s
`_validate_parent_reference` reuses `visible_categories`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.budgets.models import Budget
from app.budgets.queries import visible_budgets
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
