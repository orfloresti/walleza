"""FastAPI routes for the `transfer-management` capability (design D14,
D41, D43). `APIRouter(dependencies=[Depends(require_membership)])` —
every route on this router inherits the membership gate with no
per-route opt-in required (design D14), mirroring
`app/transactions/router.py` exactly;
`backend/tests/test_route_coverage.py` is the structural proof no future
route on this router escapes it.

Deliberately NO PATCH/PUT route (design D43, proposal T6): a transfer's
fields, once created, can only be corrected by deleting and recreating
it. This absence is what makes the spec's "no such route is registered"
scenario a genuine 405 from FastAPI's own routing, not an
application-level decision returning 405/409.
"""

from __future__ import annotations

import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import WorkspaceScope, require_membership
from app.transfers import schemas, service

router = APIRouter(tags=["transfers"], dependencies=[Depends(require_membership)])


@router.get("/api/transfers", response_model=list[schemas.TransferOut])
def list_transfers(
    account_id: uuid.UUID | None = Query(default=None),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.TransferOut]:
    transfers = service.list_transfers(
        db, scope=scope, account_id=account_id, date_from=date_from, date_to=date_to
    )
    return [schemas.TransferOut.model_validate(t) for t in transfers]


@router.post("/api/transfers", response_model=schemas.TransferOut, status_code=201)
def create_transfer(
    body: schemas.TransferCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TransferOut:
    try:
        transfer = service.create_transfer(
            db,
            scope=scope,
            from_account_id=body.from_account_id,
            to_account_id=body.to_account_id,
            from_amount=body.from_amount,
            occurred_on=body.occurred_on,
            notes=body.notes,
            created_by_user_id=scope.user_id,
        )
    except service.TransferValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return schemas.TransferOut.model_validate(transfer)


@router.get("/api/transfers/{transfer_id}", response_model=schemas.TransferOut)
def get_transfer(
    transfer_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.TransferOut:
    try:
        transfer = service.get_transfer(db, scope=scope, transfer_id=transfer_id)
    except service.TransferNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transfer not found") from exc
    return schemas.TransferOut.model_validate(transfer)


@router.delete("/api/transfers/{transfer_id}", status_code=204)
def delete_transfer(
    transfer_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> None:
    try:
        service.delete_transfer(db, scope=scope, transfer_id=transfer_id)
    except service.TransferNotFoundError as exc:
        raise HTTPException(status_code=404, detail="transfer not found") from exc
    db.commit()
