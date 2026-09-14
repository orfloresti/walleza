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


@router.get("/api/budgets", response_model=list[schemas.BudgetOut])
def list_budgets(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.BudgetOut]:
    budgets = service.list_budgets(db, scope=scope)
    return [schemas.BudgetOut.model_validate(budget) for budget in budgets]


@router.post("/api/budgets", response_model=schemas.BudgetOut, status_code=201)
def create_budget(
    body: schemas.BudgetCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetOut:
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
    return schemas.BudgetOut.model_validate(budget)


@router.get("/api/budgets/{budget_id}", response_model=schemas.BudgetOut)
def get_budget(
    budget_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetOut:
    try:
        budget = service.get_budget(db, scope=scope, budget_id=budget_id)
    except service.BudgetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="budget not found") from exc
    return schemas.BudgetOut.model_validate(budget)


@router.patch("/api/budgets/{budget_id}", response_model=schemas.BudgetOut)
def update_budget(
    budget_id: uuid.UUID,
    body: schemas.BudgetUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.BudgetOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        budget = service.update_budget(db, scope=scope, budget_id=budget_id, changes=changes)
    except service.BudgetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="budget not found") from exc
    except service.BudgetValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return schemas.BudgetOut.model_validate(budget)


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
