"""FastAPI routes for the `account-management`/`account-visibility`
capabilities (design D14/D15/D16/D18/D19).

`APIRouter(dependencies=[Depends(require_membership)])` — every route on
this router inherits the membership gate with no per-route opt-in
required (design D14); `backend/tests/test_route_coverage.py` is the
structural proof no future route on this router escapes it.

`DELETE /api/accounts/{id}` is deliberately NOT defined here — the
design's Interfaces/Contracts table marks it "Not exposed in Phase 1 —
archival replaces deletion" (decision 6: `archived` is the one collapsed
lifecycle state, there is no separate hide/delete state). Archiving is
`PATCH /api/accounts/{id}` with `{"archived": true}`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.accounts import schemas, service
from app.db import get_db
from app.deps import WorkspaceScope, require_membership

router = APIRouter(tags=["accounts"], dependencies=[Depends(require_membership)])


@router.get("/api/accounts", response_model=list[schemas.AccountOut])
def list_accounts(
    archived: bool = Query(default=False),
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> list[schemas.AccountOut]:
    accounts = service.list_accounts(db, scope=scope, archived=archived)
    return [schemas.AccountOut.model_validate(account) for account in accounts]


@router.post("/api/accounts", response_model=schemas.AccountOut, status_code=201)
def create_account(
    body: schemas.AccountCreateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.AccountOut:
    account = service.create_account(
        db,
        scope=scope,
        name=body.name,
        currency=body.currency,
        exchange_rate=body.exchange_rate,
        initial_funds=body.initial_funds,
        is_personal=body.is_personal,
    )
    db.commit()
    return schemas.AccountOut.model_validate(account)


@router.get("/api/accounts/{account_id}", response_model=schemas.AccountOut)
def get_account(
    account_id: uuid.UUID,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.AccountOut:
    try:
        account = service.get_account(db, scope=scope, account_id=account_id)
    except service.AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc
    return schemas.AccountOut.model_validate(account)


@router.patch("/api/accounts/{account_id}", response_model=schemas.AccountOut)
def update_account(
    account_id: uuid.UUID,
    body: schemas.AccountUpdateIn,
    scope: WorkspaceScope = Depends(require_membership),
    db: Session = Depends(get_db),
) -> schemas.AccountOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        account = service.update_account(db, scope=scope, account_id=account_id, changes=changes)
    except service.AccountNotFoundError as exc:
        raise HTTPException(status_code=404, detail="account not found") from exc
    db.commit()
    return schemas.AccountOut.model_validate(account)
