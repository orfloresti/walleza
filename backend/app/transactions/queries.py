"""Scope-aware query builder for the `transaction-visibility` capability
(design D30). `visible_transactions` is the ONLY sanctioned way to build a
transaction-scoped `Select`: it takes a `WorkspaceScope` — which only
`app.deps.require_membership` can produce — as its first positional
argument, mirroring `app.accounts.queries.visible_accounts` and
`app.categories.queries.visible_categories` (design D14's second
structural layer: a scopeless query is unwritable).

A transaction carries NO visibility state of its own (proposal decision
#6): it JOINs `visible_accounts(scope)` — called with no `archived`
kwarg, exactly per D30 — as a subquery, so D15's predicate keeps exactly
one definition site. Category filtering is an `EXISTS` against
`transaction_category_split`, never a JOIN: a JOIN would change row
cardinality the moment a transaction has more than one split line, which
would silently double-count a future `SUM` aggregate (P5/P6) wrapped
around this same `Select` — precisely the hazard D16 exists to prevent.
"""

from __future__ import annotations

import datetime
import uuid

import sqlalchemy as sa
from sqlalchemy.sql import Select

from app.accounts.queries import visible_accounts
from app.deps import WorkspaceScope
from app.transactions.models import OcrStatus, Transaction, TransactionCategorySplit


def visible_transactions(
    scope: WorkspaceScope,
    *,
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    type: str | None = None,
) -> Select:
    """Design D30's exact shape: JOIN `visible_accounts(scope)` (no
    `archived` kwarg — archiving an account must not make its transaction
    history disappear, mirroring `get_account`'s own reasoning) as a
    subquery, then apply each optional filter only when given.

    `Transaction.workspace_id == scope.workspace_id` is redundant with the
    JOIN and kept anyway: it carries the `(workspace_id, occurred_on
    DESC)` feed index and keeps the scope assertion true even if a future
    phase reassigns an account to a different workspace.
    """
    accounts = visible_accounts(scope).subquery()
    query = (
        sa.select(Transaction)
        .join(accounts, Transaction.account_id == accounts.c.id)
        .where(Transaction.workspace_id == scope.workspace_id)
        .where(  # design D120: an OCR draft is not a real transaction yet
            sa.or_(
                Transaction.ocr_status.is_(None),
                Transaction.ocr_status == OcrStatus.CONFIRMED,
            )
        )
    )
    if account_id is not None:
        query = query.where(Transaction.account_id == account_id)
    if type is not None:
        query = query.where(Transaction.type == type)
    if date_from is not None:
        query = query.where(Transaction.occurred_on >= date_from)
    if date_to is not None:
        query = query.where(Transaction.occurred_on <= date_to)
    if category_id is not None:
        query = query.where(
            sa.exists().where(
                sa.and_(
                    TransactionCategorySplit.transaction_id == Transaction.id,
                    TransactionCategorySplit.category_id == category_id,
                )
            )
        )
    return query


def ocr_draft_transactions(scope: WorkspaceScope) -> Select:
    """Design D120's deliberately narrow complement of
    `visible_transactions`'s draft-exclusion predicate. Returns ONLY
    in-progress OCR draft rows (`ocr_status` set and not yet
    `confirmed`) — the exact opposite selection from the sanctioned
    default path above.

    There is no `include_drafts=` kwarg on `visible_transactions` on
    purpose (design D120's rationale): a boolean flag would make the
    dangerous "see everything" behavior reachable from the one path every
    financial aggregate builds on. This function exists so that seeing a
    draft always requires importing a differently-named, narrowly-scoped
    helper — greppable and AST-checkable (see
    `tests/transactions/test_draft_containment.py`) — rather than passing
    an easy-to-mistype argument to the shared chokepoint.

    Used only by the draft-lifecycle code paths (draft creation, poll,
    confirm, and — critically — the `DELETE` endpoint, since a draft row
    is no longer visible through `visible_transactions` once D120 lands,
    but must still be resolvable so the user can discard it)."""
    accounts = visible_accounts(scope).subquery()
    return (
        sa.select(Transaction)
        .join(accounts, Transaction.account_id == accounts.c.id)
        .where(Transaction.workspace_id == scope.workspace_id)
        .where(Transaction.ocr_status.is_not(None))
        .where(Transaction.ocr_status != OcrStatus.CONFIRMED)
    )


def count_ocr_drafts_created_today(
    scope: WorkspaceScope, *, since: datetime.datetime
) -> Select:
    """Design D122: the daily rate-limit count. Counts EVERY row for the
    workspace whose `ocr_status` is set at all (`IS NOT NULL`) —
    `pending_ocr`, `extracted`, `extraction_failed`, AND `confirmed` — with
    `created_at >= since` (the caller passes UTC-midnight-of-today).
    Deliberately counts by `workspace_id` alone, with NO join to
    `visible_accounts`: the cost (a Textract call) is already spent
    regardless of which account the draft was attached to, and a workspace
    member cannot dodge the cap by targeting a different account within
    the same workspace. Served by `ix_transaction_ocr_status
    (workspace_id, ocr_status) WHERE ocr_status IS NOT NULL`."""
    return (
        sa.select(sa.func.count())
        .select_from(Transaction)
        .where(Transaction.workspace_id == scope.workspace_id)
        .where(Transaction.ocr_status.is_not(None))
        .where(Transaction.created_at >= since)
    )
