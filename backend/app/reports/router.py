"""FastAPI routes for the `report-category-breakdown` and
`report-default-currency` capabilities (design D88). Every route inherits
the membership gate with no per-route opt-in required, mirroring
`app/budgets/router.py` exactly.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import WorkspaceScope, require_membership
from app.reports import schemas, service

router = APIRouter(tags=["reports"], dependencies=[Depends(require_membership)])


@router.get("/api/reports/category-breakdown", response_model=schemas.CategoryBreakdownOut)
def get_category_breakdown(
    date_from: date = Query(...),
    date_to: date = Query(...),
    currency: str = Query(...),
    type: str = Query("expense"),
    account_id: uuid.UUID | None = Query(default=None),
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.CategoryBreakdownOut:
    try:
        rows = service.category_breakdown(
            db,
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            type=type,
            account_id=account_id,
        )
    except service.ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return schemas.CategoryBreakdownOut(
        currency=currency,
        date_from=date_from,
        date_to=date_to,
        slices=[
            schemas.CategorySliceOut(
                category_id=category.id,
                name=category.name,
                parent_id=category.parent_id,
                own=own,
                total=total,
            )
            for category, own, total in rows
        ],
    )


@router.get("/api/reports/default-currency", response_model=schemas.DefaultCurrencyOut)
def get_default_currency(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.DefaultCurrencyOut:
    return schemas.DefaultCurrencyOut(currency=service.default_currency(db, scope=scope))
