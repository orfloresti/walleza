"""FastAPI routes for the `transaction-templates` capability (design D14,
D18, D45-D56). `APIRouter(dependencies=[Depends(require_membership)])` —
every route on this router inherits the membership gate with no per-route
opt-in required (design D14), mirroring `app/transactions/router.py` and
`app/transfers/router.py` exactly.

`POST /api/templates/{id}/apply` (design D56) creates a real `Transaction`
by delegating to `app.templates.service.apply_template`, which itself
reuses `app.transactions.service.create_transaction`/`replace_splits`
verbatim (R8) — errors from that reused write path (an invalid account or
a stale/deleted split category) surface here as the SAME 422 a manual
`POST /api/transactions` would produce.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import WorkspaceScope, require_membership
from app.templates import schemas, service
from app.templates.models import TransactionTemplate
from app.transactions import schemas as transaction_schemas
from app.transactions import service as transactions_service

router = APIRouter(tags=["templates"], dependencies=[Depends(require_membership)])


def _to_out(db: Session, template: TransactionTemplate) -> schemas.TemplateOut:
    splits = service.list_template_splits(db, template_id=template.id)
    return schemas.TemplateOut(
        id=template.id,
        workspace_id=template.workspace_id,
        account_id=template.account_id,
        name=template.name,
        position=template.position,
        type=template.type,
        amount=template.amount,
        notes=template.notes,
        created_by_user_id=template.created_by_user_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
        splits=[schemas.TemplateSplitOut.model_validate(s) for s in splits],
    )


def _to_transaction_out(
    db: Session, transaction
) -> transaction_schemas.TransactionOut:
    """Mirrors `app.transactions.router._to_out` — duplicated locally
    rather than imported since that helper is private to that module."""
    splits = transactions_service.list_splits(db, transaction_id=transaction.id)
    return transaction_schemas.TransactionOut(
        id=transaction.id,
        workspace_id=transaction.workspace_id,
        account_id=transaction.account_id,
        type=transaction.type,
        amount=transaction.amount,
        occurred_on=transaction.occurred_on,
        notes=transaction.notes,
        is_refund=transaction.is_refund,
        checked=transaction.checked,
        photo_content_type=transaction.photo_content_type,
        photo_uploaded_at=transaction.photo_uploaded_at,
        created_by_user_id=transaction.created_by_user_id,
        created_at=transaction.created_at,
        updated_at=transaction.updated_at,
        splits=[transaction_schemas.SplitOut.model_validate(s) for s in splits],
    )


@router.get("/api/templates", response_model=list[schemas.TemplateOut])
def list_templates(
    account_id: uuid.UUID | None = None,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.TemplateOut]:
    templates = service.list_templates(db, scope=scope, account_id=account_id)
    return [_to_out(db, t) for t in templates]


@router.post("/api/templates", response_model=schemas.TemplateOut, status_code=201)
def create_template(
    body: schemas.TemplateCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TemplateOut:
    try:
        template = service.create_template(
            db,
            scope=scope,
            account_id=body.account_id,
            name=body.name,
            type=body.type,
            amount=body.amount,
            notes=body.notes,
            position=body.position,
            created_by_user_id=scope.user_id,
            splits=body.splits,
        )
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TemplateSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, template)


@router.get("/api/templates/{template_id}", response_model=schemas.TemplateOut)
def get_template(
    template_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TemplateOut:
    try:
        template = service.get_template(db, scope=scope, template_id=template_id)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    return _to_out(db, template)


@router.patch("/api/templates/{template_id}", response_model=schemas.TemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: schemas.TemplateUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TemplateOut:
    raw = body.model_dump(exclude_unset=True)
    splits_provided = "splits" in raw
    raw.pop("splits", None)
    try:
        template = service.update_template(
            db,
            scope=scope,
            template_id=template_id,
            changes=raw,
            splits=body.splits,
            splits_provided=splits_provided,
        )
    except service.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    except service.TemplateValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.TemplateSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, template)


@router.delete("/api/templates/{template_id}", status_code=204)
def delete_template(
    template_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_template(db, scope=scope, template_id=template_id)
    except service.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    db.commit()


@router.post(
    "/api/templates/{template_id}/apply",
    response_model=transaction_schemas.TransactionOut,
    status_code=201,
)
def apply_template(
    template_id: uuid.UUID,
    body: schemas.TemplateApplyIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> transaction_schemas.TransactionOut:
    try:
        transaction = service.apply_template(
            db, scope=scope, template_id=template_id, occurred_on=body.occurred_on
        )
    except service.TemplateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="template not found") from exc
    except transactions_service.TransactionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except transactions_service.TransactionSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_transaction_out(db, transaction)
