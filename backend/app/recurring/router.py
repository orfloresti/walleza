"""FastAPI routes for the `recurring-transactions` capability (design D14,
D18, D45-D56, D56). `APIRouter(dependencies=[Depends(require_membership)])`
— every route on this router inherits the membership gate with no
per-route opt-in required (design D14), mirroring
`app/transactions/router.py` and `app/templates/router.py` exactly.

Design D56: the Subscriptions view is `GET /api/recurring?is_subscription=
true` — no separate route, entity, or service exists for it anywhere in
this module.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import WorkspaceScope, require_membership
from app.recurring import schemas, service
from app.recurring.models import RecurringTransaction

router = APIRouter(tags=["recurring"], dependencies=[Depends(require_membership)])


def _to_out(db: Session, recurring: RecurringTransaction) -> schemas.RecurringOut:
    splits = service.list_recurring_splits(db, recurring_id=recurring.id)
    return schemas.RecurringOut(
        id=recurring.id,
        workspace_id=recurring.workspace_id,
        account_id=recurring.account_id,
        type=recurring.type,
        amount=recurring.amount,
        notes=recurring.notes,
        is_refund=recurring.is_refund,
        is_subscription=recurring.is_subscription,
        repeat_every=recurring.repeat_every,
        period=recurring.period,
        starts_on=recurring.starts_on,
        occurrence_index=recurring.occurrence_index,
        next_date=recurring.next_date,
        ends_on=recurring.ends_on,
        reminder_days_before=recurring.reminder_days_before,
        last_reminded_for_date=recurring.last_reminded_for_date,
        reminder_locale=recurring.reminder_locale,
        created_by_user_id=recurring.created_by_user_id,
        created_at=recurring.created_at,
        updated_at=recurring.updated_at,
        splits=[schemas.RecurringSplitOut.model_validate(s) for s in splits],
    )


@router.get("/api/recurring", response_model=list[schemas.RecurringOut])
def list_recurring(
    account_id: uuid.UUID | None = Query(default=None),
    is_subscription: bool | None = Query(default=None),
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.RecurringOut]:
    recurring = service.list_recurring(
        db, scope=scope, account_id=account_id, is_subscription=is_subscription
    )
    return [_to_out(db, r) for r in recurring]


@router.post("/api/recurring", response_model=schemas.RecurringOut, status_code=201)
def create_recurring(
    body: schemas.RecurringCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.RecurringOut:
    try:
        recurring = service.create_recurring(
            db,
            scope=scope,
            account_id=body.account_id,
            type=body.type,
            amount=body.amount,
            notes=body.notes,
            is_refund=body.is_refund,
            is_subscription=body.is_subscription,
            repeat_every=body.repeat_every,
            period=body.period,
            starts_on=body.starts_on,
            ends_on=body.ends_on,
            reminder_days_before=body.reminder_days_before,
            reminder_locale=body.reminder_locale,
            created_by_user_id=scope.user_id,
            splits=body.splits,
        )
    except service.RecurringValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.RecurringSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, recurring)


@router.get("/api/recurring/{recurring_id}", response_model=schemas.RecurringOut)
def get_recurring(
    recurring_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.RecurringOut:
    try:
        recurring = service.get_recurring(db, scope=scope, recurring_id=recurring_id)
    except service.RecurringNotFoundError as exc:
        raise HTTPException(status_code=404, detail="recurring transaction not found") from exc
    return _to_out(db, recurring)


@router.patch("/api/recurring/{recurring_id}", response_model=schemas.RecurringOut)
def update_recurring(
    recurring_id: uuid.UUID,
    body: schemas.RecurringUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.RecurringOut:
    raw = body.model_dump(exclude_unset=True)
    splits_provided = "splits" in raw
    raw.pop("splits", None)
    try:
        recurring = service.update_recurring(
            db,
            scope=scope,
            recurring_id=recurring_id,
            changes=raw,
            splits=body.splits,
            splits_provided=splits_provided,
        )
    except service.RecurringNotFoundError as exc:
        raise HTTPException(status_code=404, detail="recurring transaction not found") from exc
    except service.RecurringValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.RecurringSplitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _to_out(db, recurring)


@router.delete("/api/recurring/{recurring_id}", status_code=204)
def delete_recurring(
    recurring_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_recurring(db, scope=scope, recurring_id=recurring_id)
    except service.RecurringNotFoundError as exc:
        raise HTTPException(status_code=404, detail="recurring transaction not found") from exc
    db.commit()
