"""Business logic for the `transaction-templates` capability (design
D45-D56). Every read/write here is built ONLY on top of
`app.templates.queries.visible_templates` (design D14's second structural
layer: a scopeless template query is unwritable) — this module never
resolves membership itself and never builds a competing query path,
mirroring `app.transactions.service` exactly.

`apply_template` (design D56, R8) reuses
`app.transactions.service.create_transaction`/`replace_splits` VERBATIM —
the created row is created through the exact same write path a manual
`POST /api/transactions` would use, so a generated transaction is never
distinguishable from (or subject to different validation than) a manually
entered one. The template row itself is never touched by an apply.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import UTC
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.accounts.models import Account
from app.accounts.queries import visible_accounts
from app.categories.models import Category
from app.categories.queries import visible_categories
from app.deps import WorkspaceScope
from app.templates import schemas
from app.templates.models import TransactionTemplate, TransactionTemplateSplit
from app.templates.queries import visible_templates
from app.transactions import schemas as transaction_schemas
from app.transactions import service as transactions_service
from app.transactions.models import Transaction


class TemplateNotFoundError(Exception):
    """Raised whenever a target template id falls outside
    `visible_templates` for the caller's scope. Design D18's 404 convention
    (mirrors `TransactionNotFoundError` exactly): a 403 would confirm the
    row exists at all."""


class TemplateValidationError(Exception):
    """Raised when `account_id` does not resolve inside the caller's own
    `visible_accounts(scope)`. Mapped to 422 by the router — never 404,
    because `account_id` is a request BODY field, not a resource being
    fetched by id (mirrors `TransactionValidationError` exactly)."""


class TemplateSplitValidationError(Exception):
    """Raised by `replace_template_splits` when a split line's
    `category_id` does not resolve inside the caller's own workspace, a
    `category_id` is repeated within the same request, or the split
    amounts do not sum EXACTLY to the template's own amount. Mapped to 422
    by the router. Mirrors `TransactionSplitValidationError` exactly."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def _validate_account_reference(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID
) -> None:
    """Mirrors `app.transactions.service._validate_account_reference`
    exactly: `account_id` must resolve inside `visible_accounts(scope)`."""
    account = db.execute(
        visible_accounts(scope).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise TemplateValidationError("account not found")


def list_templates(
    db: Session, *, scope: WorkspaceScope, account_id: uuid.UUID | None = None
) -> list[TransactionTemplate]:
    query = visible_templates(scope, account_id=account_id).order_by(
        TransactionTemplate.position, TransactionTemplate.created_at
    )
    return list(db.execute(query).scalars())


def get_template(
    db: Session, *, scope: WorkspaceScope, template_id: uuid.UUID
) -> TransactionTemplate:
    template = db.execute(
        visible_templates(scope).where(TransactionTemplate.id == template_id)
    ).scalar_one_or_none()
    if template is None:
        raise TemplateNotFoundError("template not found")
    return template


def create_template(
    db: Session,
    *,
    scope: WorkspaceScope,
    account_id: uuid.UUID,
    name: str,
    type: str,
    amount: Decimal,
    notes: str | None,
    position: int,
    created_by_user_id: uuid.UUID,
    splits: list[schemas.TemplateSplitIn] | None = None,
) -> TransactionTemplate:
    _validate_account_reference(db, scope=scope, account_id=account_id)

    now = _now()
    template = TransactionTemplate(
        id=uuid.uuid4(),
        workspace_id=scope.workspace_id,
        account_id=account_id,
        name=name,
        position=position,
        type=type,
        amount=amount,
        notes=notes,
        created_by_user_id=created_by_user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(template)
    # `replace_template_splits` validates BEFORE its own `db.flush()`, so a
    # rejected request never flushes the pending `template` insert either.
    replace_template_splits(db, scope=scope, template=template, lines=splits or [])
    return template


def update_template(
    db: Session,
    *,
    scope: WorkspaceScope,
    template_id: uuid.UUID,
    changes: dict[str, object],
    splits: list[schemas.TemplateSplitIn] | None = None,
    splits_provided: bool = False,
) -> TransactionTemplate:
    template = get_template(db, scope=scope, template_id=template_id)

    if "account_id" in changes and changes["account_id"] is not None:
        _validate_account_reference(
            db, scope=scope, account_id=changes["account_id"]  # type: ignore[arg-type]
        )

    if splits_provided:
        replace_template_splits(db, scope=scope, template=template, lines=splits or [])
    elif "amount" in changes:
        existing = list_template_splits(db, template_id=template.id)
        if existing:
            new_amount = changes["amount"]
            total = sum((line.amount for line in existing), start=Decimal(0))
            if total != new_amount:
                raise TemplateSplitValidationError(
                    f"existing splits ({total}) no longer sum to the updated "
                    f"template amount ({new_amount}); update splits too"
                )

    for field, value in changes.items():
        setattr(template, field, value)
    template.updated_at = _now()
    db.flush()
    return template


def delete_template(db: Session, *, scope: WorkspaceScope, template_id: uuid.UUID) -> None:
    template = get_template(db, scope=scope, template_id=template_id)
    db.delete(template)
    db.flush()


def list_template_splits(
    db: Session, *, template_id: uuid.UUID
) -> list[TransactionTemplateSplit]:
    return list(
        db.execute(
            sa.select(TransactionTemplateSplit)
            .where(TransactionTemplateSplit.template_id == template_id)
            .order_by(TransactionTemplateSplit.id)
        ).scalars()
    )


def replace_template_splits(
    db: Session,
    *,
    scope: WorkspaceScope,
    template: TransactionTemplate,
    lines: list[schemas.TemplateSplitIn],
) -> None:
    """The ONLY function that ever writes a `transaction_template_split`
    row. Mirrors `app.transactions.service.replace_splits` exactly: whole
    -set replacement, category visibility + exact Decimal sum validated
    BEFORE any row is deleted or inserted."""
    if lines:
        category_ids = {line.category_id for line in lines}
        if len(category_ids) != len(lines):
            raise TemplateSplitValidationError(
                "a category cannot appear more than once in the same split set"
            )

        visible_ids = {
            row.id
            for row in db.execute(
                visible_categories(scope).where(Category.id.in_(category_ids))
            ).scalars()
        }
        missing = category_ids - visible_ids
        if missing:
            raise TemplateSplitValidationError(
                "one or more split categories are not visible in this workspace"
            )

        total = sum((line.amount for line in lines), start=Decimal(0))
        if total != template.amount:
            raise TemplateSplitValidationError(
                f"split amounts must sum exactly to the template amount "
                f"(got {total}, expected {template.amount})"
            )

    db.execute(
        sa.delete(TransactionTemplateSplit).where(
            TransactionTemplateSplit.template_id == template.id
        )
    )
    for line in lines:
        db.add(
            TransactionTemplateSplit(
                id=uuid.uuid4(),
                template_id=template.id,
                category_id=line.category_id,
                amount=line.amount,
            )
        )
    db.flush()


def apply_template(
    db: Session,
    *,
    scope: WorkspaceScope,
    template_id: uuid.UUID,
    occurred_on: datetime.date | None = None,
) -> Transaction:
    """Design D56/R8: creates a real `Transaction` (+ splits, if any) via
    `transactions.service.create_transaction`/`replace_splits` VERBATIM.
    The template row is never modified — applying it twice creates two
    independent transactions, both matching the template's own
    account/type/amount/splits.

    A stale split `category_id` (deleted since the template was saved) or
    a corrupted `account_id` is caught by `create_transaction`'s own
    `_validate_account_reference`/`replace_splits` checks — no bespoke
    revalidation exists here, since reusing the exact same write path is
    the whole point of R8. An archived account is a valid apply target,
    exactly as it is a valid manual-entry target (`visible_accounts(scope)`
    is called with no `archived` filter throughout)."""
    template = get_template(db, scope=scope, template_id=template_id)
    template_splits = list_template_splits(db, template_id=template.id)

    return transactions_service.create_transaction(
        db,
        scope=scope,
        account_id=template.account_id,
        type=template.type,
        amount=template.amount,
        occurred_on=occurred_on or datetime.datetime.now(UTC).date(),
        notes=template.notes,
        is_refund=False,
        checked=False,
        created_by_user_id=scope.user_id,
        splits=[
            transaction_schemas.SplitIn(category_id=line.category_id, amount=line.amount)
            for line in template_splits
        ]
        or None,
    )
