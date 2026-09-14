"""FastAPI routes for the `budget-management` capability (design D14,
D66-D70). `APIRouter(dependencies=[Depends(require_membership)])` — every
route on this router inherits the membership gate with no per-route
opt-in required (design D14), mirroring `app/categories/router.py`
exactly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.budgets import schemas, service
from app.db import get_db
from app.deps import WorkspaceScope, require_membership

router = APIRouter(tags=["budgets"], dependencies=[Depends(require_membership)])


def _with_progress(budget, progress: service.BudgetProgress) -> schemas.BudgetWithProgressOut:
    return schemas.BudgetWithProgressOut(
        **schemas.BudgetOut.model_validate(budget).model_dump(),
        progress=schemas.BudgetProgressOut(
            limit=progress.limit,
            spent=progress.spent,
            remaining=progress.remaining,
            percent=progress.percent,
            status=progress.status,
            period_start=progress.period_start,
            period_end=progress.period_end,
        ),
    )


@router.get("/api/budgets", response_model=list[schemas.BudgetWithProgressOut])
def list_budgets(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.BudgetWithProgressOut]:
    pairs = service.list_budgets_with_progress(db, scope=scope)
    return [_with_progress(budget, progress) for budget, progress in pairs]


@router.post("/api/budgets", response_model=schemas.BudgetWithProgressOut, status_code=201)
def create_budget(
    body: schemas.BudgetCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetWithProgressOut:
    try:
        budget = service.create_budget(
            db,
            scope=scope,
            category_id=body.category_id,
            account_id=body.account_id,
            name=body.name,
            amount=body.amount,
            currency=body.currency,
        )
    except service.BudgetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _, progress = service.get_budget_progress(db, scope=scope, budget_id=budget.id)
    return _with_progress(budget, progress)


@router.get("/api/budgets/{budget_id}", response_model=schemas.BudgetWithProgressOut)
def get_budget(
    budget_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetWithProgressOut:
    try:
        budget, progress = service.get_budget_progress(db, scope=scope, budget_id=budget_id)
    except service.BudgetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="budget not found") from exc
    return _with_progress(budget, progress)


@router.patch("/api/budgets/{budget_id}", response_model=schemas.BudgetWithProgressOut)
def update_budget(
    budget_id: uuid.UUID,
    body: schemas.BudgetUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetWithProgressOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        budget = service.update_budget(db, scope=scope, budget_id=budget_id, changes=changes)
    except service.BudgetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="budget not found") from exc
    except service.BudgetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _, progress = service.get_budget_progress(db, scope=scope, budget_id=budget.id)
    return _with_progress(budget, progress)


@router.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(
    budget_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_budget(db, scope=scope, budget_id=budget_id)
    except service.BudgetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="budget not found") from exc
    db.commit()
