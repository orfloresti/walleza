"""FastAPI routes for the `category-management` capability (design D14,
D28, D29). `APIRouter(dependencies=[Depends(require_membership)])` —
every route on this router inherits the membership gate with no
per-route opt-in required (design D14), mirroring
`app/accounts/router.py` exactly.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.categories import schemas, service
from app.db import get_db
from app.deps import WorkspaceScope, require_membership

router = APIRouter(tags=["categories"], dependencies=[Depends(require_membership)])


@router.get("/api/categories", response_model=list[schemas.CategoryOut])
def list_categories(
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.CategoryOut]:
    categories = service.list_categories(db, scope=scope)
    return [schemas.CategoryOut.model_validate(category) for category in categories]


@router.post("/api/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    body: schemas.CategoryCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.CategoryOut:
    try:
        category = service.create_category(
            db,
            scope=scope,
            name=body.name,
            icon=body.icon,
            type=body.type,
            parent_id=body.parent_id,
        )
    except service.CategoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return schemas.CategoryOut.model_validate(category)


@router.get("/api/categories/{category_id}", response_model=schemas.CategoryOut)
def get_category(
    category_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.CategoryOut:
    try:
        category = service.get_category(db, scope=scope, category_id=category_id)
    except service.CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="category not found") from exc
    return schemas.CategoryOut.model_validate(category)


@router.patch("/api/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: schemas.CategoryUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.CategoryOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        category = service.update_category(
            db, scope=scope, category_id=category_id, changes=changes
        )
    except service.CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="category not found") from exc
    except service.CategoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return schemas.CategoryOut.model_validate(category)


@router.delete("/api/categories/{category_id}", status_code=204)
def delete_category(
    category_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_category(db, scope=scope, category_id=category_id)
    except service.CategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail="category not found") from exc
    except service.CategoryDeleteBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
