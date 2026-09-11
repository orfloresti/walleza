"""Occurrence generation core for the `scheduled-occurrence-generation`
capability (design D45-D49, D45's "Occurrence Generation Core" PR).

This module is the phase's single highest-risk file: it is the ONLY code
path in the whole product that iterates every workspace's data with NO
authenticated caller and NO `WorkspaceScope` handed to it from a request.
It is never imported by `app.main` and registers no route — its only
caller is `app.scheduler.handler`, itself invoked only by an EventBridge
rule targeting a SEPARATE Lambda function with no Function URL (design
D45). Every safety property below is enforced by re-deriving state from
durable server-side rows, never by trusting anything passed in.

Two mechanisms carry the phase's risk, matching design's own framing:

- `scope_for_recurrence` (D46): derives a `WorkspaceScope` from the
  recurrence ROW ITSELF (`workspace_id`/`created_by_user_id`), re-reading
  `workspace_member` exactly as `app.deps.require_membership` does. A
  membership row that no longer exists returns `None` — that recurrence
  PAUSES (cursor untouched, nothing written), never falls back to a
  widened or fabricated scope.
- `shift` (D49): recomputes occurrence *i* from the recurrence's
  IMMUTABLE `starts_on` anchor every time, never from the previous
  `next_date`. This is deliberately stdlib-only (`datetime.timedelta` +
  `calendar.monthrange` clamping) — design D49 explicitly rejects
  `dateutil.relativedelta` here: applied iteratively (not anchor-based)
  ANY library drifts the same way (Jan 31 -> Feb 28 -> Mar 28 -> Apr 28),
  so the fix is the anchor formulation, not the library, and a declared
  runtime dependency for ten lines of clamped month arithmetic is not
  worth the added import surface in a module that runs in a second,
  security-sensitive Lambda.

Idempotency (D47) is a database constraint, not a Python-side check:
`recurring_occurrence`'s primary key `(recurring_transaction_id,
occurrence_date)` is the authority. `INSERT ... ON CONFLICT DO NOTHING`
with `rowcount == 0` means "already generated" — this holds regardless of
read timing, so two overlapping runs can never both post for the same
occurrence. `SELECT ... FOR UPDATE SKIP LOCKED` per recurrence is the
belt to that constraint's braces: a session that cannot acquire the lock
treats the row as owned by another run and moves on to the next one,
rather than blocking or racing it.

Catch-up (D48) generates every missed occurrence, bounded by
`generation_max_catchup_per_run` (default 120) per recurrence per run.
Hitting the cap PAUSES — commits whatever was generated and leaves the
cursor mid-backlog — it never fast-forwards past the remainder, because a
skipped occurrence would be a permanently wrong financial record, not a
cosmetic gap.

Commit granularity (D47): ONE commit per recurrence, wrapping the whole
per-recurrence catch-up loop (occurrence inserts, `create_transaction`/
`replace_splits` calls, and the cursor advance) in a single DB
transaction. A mid-run timeout or an exception on recurrence N therefore
leaves recurrences 1..N-1 durably committed; recurrence N itself rolls
back to its pre-loop state (paused, not partially written) and the next
daily run picks it back up from its last durable cursor position. This is
NOT one commit for the whole batch — a single commit for 500 due
recurrences would mean a crash on the 499th loses all 498 that already
completed successfully.
"""

from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import WorkspaceScope
from app.recurring.models import (
    RecurringOccurrence,
    RecurringTransaction,
    RecurringTransactionSplit,
)
from app.transactions.schemas import SplitIn
from app.transactions.service import create_transaction
from app.workspace.models import WorkspaceMember

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {"day": 1, "week": 7}


def shift(anchor: date, period: str, n: int) -> date:
    """Occurrence *n* counted from the IMMUTABLE anchor — never from the
    previous occurrence (design D49). For a monthly recurrence starting
    Jan 31: n=0 -> Jan 31, n=1 -> Feb 28, n=2 -> **Mar 31** (not Mar 28),
    because every call re-clamps day 31 against THAT month's own length,
    instead of inheriting February's clamped 28."""
    if period in _PERIOD_DAYS:
        return anchor + timedelta(days=_PERIOD_DAYS[period] * n)
    months = n * (12 if period == "year" else 1)
    total = anchor.month - 1 + months
    year, month = anchor.year + total // 12, total % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def scope_for_recurrence(db: Session, r: RecurringTransaction) -> WorkspaceScope | None:
    """Design D46: both values come off the ROW, never from a request.
    Membership is re-read from the database exactly as
    `app.deps.require_membership` does — `None` means "pause", never a
    widened or fabricated scope. A recurrence's `workspace_id` and
    `created_by_user_id` can only ever produce a scope that
    `visible_accounts`/`visible_categories` would also have produced for
    that same member, so `create_transaction`'s existing guards (D15/D22)
    apply unchanged."""
    member = db.execute(
        sa.select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == r.created_by_user_id,
            WorkspaceMember.workspace_id == r.workspace_id,
        )
    ).first()
    if member is None:
        return None
    return WorkspaceScope(user_id=r.created_by_user_id, workspace_id=r.workspace_id)


def _splits_for(db: Session, recurring_id: uuid.UUID) -> list[SplitIn]:
    rows = db.execute(
        sa.select(RecurringTransactionSplit)
        .where(RecurringTransactionSplit.recurring_transaction_id == recurring_id)
        .order_by(RecurringTransactionSplit.id)
    ).scalars()
    return [SplitIn(category_id=row.category_id, amount=row.amount) for row in rows]


def _generate_for_recurrence(db: Session, recurring_id: uuid.UUID, *, today: date) -> str:
    """Process exactly one due recurrence in its OWN database transaction
    (design D47's per-recurrence commit granularity). Returns one of:
    `"locked"` (another run owns this row right now), `"paused"` (no
    sanctioned scope — membership missing), `"generated"` (at least one
    occurrence posted), `"no_due_occurrence"` (selected by the outer
    cross-workspace scan but nothing was actually due once re-checked
    under lock, e.g. it was already fully caught up by a concurrent run),
    or `"error"` (an exception was raised and rolled back; the recurrence
    is left exactly where it was before this call — paused, not
    partially written)."""
    settings = get_settings()
    cap = settings.generation_max_catchup_per_run

    row = db.execute(
        sa.select(RecurringTransaction)
        .where(RecurringTransaction.id == recurring_id)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if row is None:
        # Either deleted since the outer scan, or another concurrent run
        # already holds this row's lock (design's Data Flow step ②:
        # "absent => another run owns it").
        db.rollback()
        return "locked"

    scope = scope_for_recurrence(db, row)
    if scope is None:
        logger.warning(
            "recurring_transaction %s paused: creator %s is no longer a member "
            "of workspace %s",
            row.id,
            row.created_by_user_id,
            row.workspace_id,
        )
        db.rollback()
        return "paused"

    try:
        generated_any = False
        iterations = 0
        while iterations < cap:
            occ = shift(row.starts_on, row.period, row.repeat_every * row.occurrence_index)
            if occ > today:
                break
            if row.ends_on is not None and occ > row.ends_on:
                break

            # `RETURNING` (rather than `CursorResult.rowcount`) is the
            # reliable way to detect whether `ON CONFLICT DO NOTHING`
            # actually inserted a row: rowcount reporting for a
            # conflict-skipped INSERT is driver-dependent, but a `RETURNING`
            # clause only ever yields rows for INSERTs that truly happened.
            result = db.execute(
                pg_insert(RecurringOccurrence)
                .values(
                    recurring_transaction_id=row.id,
                    occurrence_date=occ,
                    transaction_id=None,
                )
                .on_conflict_do_nothing(
                    index_elements=["recurring_transaction_id", "occurrence_date"]
                )
                .returning(RecurringOccurrence.recurring_transaction_id)
            )
            if result.first() is not None:
                splits = _splits_for(db, row.id)
                transaction = create_transaction(
                    db,
                    scope=scope,
                    account_id=row.account_id,
                    type=row.type,
                    amount=row.amount,
                    occurred_on=occ,
                    notes=row.notes,
                    is_refund=row.is_refund,
                    checked=False,
                    created_by_user_id=row.created_by_user_id,
                    splits=splits or None,
                )
                db.flush()
                db.execute(
                    sa.update(RecurringOccurrence)
                    .where(
                        RecurringOccurrence.recurring_transaction_id == row.id,
                        RecurringOccurrence.occurrence_date == occ,
                    )
                    .values(transaction_id=transaction.id)
                )
                generated_any = True

            # The cursor advances every iteration regardless of whether the
            # insert above actually happened — a conflict means "already
            # generated" and the run must still move past it, never retry
            # or leave the cursor pointed at an occurrence already posted.
            row.occurrence_index += 1
            row.next_date = shift(row.starts_on, row.period, row.repeat_every * row.occurrence_index)
            iterations += 1

        db.commit()
        return "generated" if generated_any else "no_due_occurrence"
    except Exception:
        db.rollback()
        logger.exception("recurring_transaction %s paused after an error mid-run", recurring_id)
        return "error"


def run(db: Session, *, today: date) -> dict[str, int]:
    """Pass A: occurrence generation. `today` is a PARAMETER, never read
    from the clock here and never from the Lambda event (design D45's
    threat case 2) — this keeps tests deterministic and the caller
    (`app.scheduler.handler`) is the only place `datetime.now()` appears.

    The due-set scan is deliberately cross-workspace and scopeless
    (design's Data Flow ①) — that is this module's entire risk surface,
    and it is why every write below re-derives its own scope per row via
    `scope_for_recurrence` instead of ever accepting one from a caller.
    """
    due_ids = list(
        db.execute(
            sa.select(RecurringTransaction.id)
            .where(RecurringTransaction.next_date <= today)
            .order_by(RecurringTransaction.next_date, RecurringTransaction.id)
        ).scalars()
    )

    counts = {"due": len(due_ids), "generated": 0, "paused": 0, "locked": 0, "errors": 0}
    for recurring_id in due_ids:
        outcome = _generate_for_recurrence(db, recurring_id, today=today)
        if outcome == "generated":
            counts["generated"] += 1
        elif outcome == "paused":
            counts["paused"] += 1
        elif outcome == "locked":
            counts["locked"] += 1
        elif outcome == "error":
            counts["errors"] += 1
    return counts
