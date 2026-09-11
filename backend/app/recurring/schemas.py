"""Pydantic request/response models for the `recurring-transactions`
capability (design's Interfaces/Contracts section, design D19/D45-D56).
This PR is CRUD-only: `next_date`, `occurrence_index`, and
`last_reminded_for_date` are server-managed cursors, settable ONLY by a
later PR's `app.recurring.generation`/reminder pass — never accepted from
the client, on create or update (spec: "`next_date` Is Server-Managed").

`reminder_days_before`/`reminder_locale` ARE part of the create/update
surface here even though the SENDING logic (`recurring-reminders`) lands
in a later PR: they are per-recurrence opt-in configuration columns on
this same row (spec: "`reminder_days_before` is nullable per-recurrence
opt-in"), so configuring them is naturally part of "full CRUD" on this
resource — only the daily send itself is deferred.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.accounts.schemas import MoneyOut

# Design decision 8: income|expense only, never transfer (R2).
RecurringType = Literal["income", "expense"]
RecurringPeriod = Literal["day", "week", "month", "year"]
ReminderLocale = Literal["en", "es"]


class RecurringSplitIn(BaseModel):
    """Mirrors `app.transactions.schemas.SplitIn` exactly. `category_id`
    MUST reference a category the caller can already see — enforced by
    `app.recurring.service.replace_recurring_splits`, not here."""

    category_id: uuid.UUID
    amount: Decimal


class RecurringSplitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    amount: MoneyOut


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    account_id: uuid.UUID
    type: RecurringType
    amount: MoneyOut
    notes: str | None
    is_refund: bool
    is_subscription: bool
    repeat_every: int
    period: RecurringPeriod
    starts_on: date
    occurrence_index: int
    next_date: date
    ends_on: date | None
    reminder_days_before: int | None
    last_reminded_for_date: date | None
    reminder_locale: ReminderLocale
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    splits: list[RecurringSplitOut] = []


class RecurringCreateIn(BaseModel):
    """`account_id` MUST reference an account the caller can already see —
    enforced by `app.recurring.service.create_recurrence`, not here.

    `next_date` has NO field here at all: the service layer initializes it
    from `starts_on` (spec: "next_date initialized to the start date").
    `ends_on`, when given, MUST NOT precede `starts_on` — enforced by the
    service layer (a cross-field rule Pydantic's per-field validation
    cannot express) AND backstopped by the DB CHECK constraint.

    No `to_account_id`/second-amount/`checked` field exists here at all
    (R2, R7 mirrored): a recurrence can never produce a `Transfer`, and
    carries no reconciliation state."""

    account_id: uuid.UUID
    type: RecurringType
    amount: Decimal
    notes: str | None = None
    is_refund: bool = False
    is_subscription: bool = False
    repeat_every: int = Field(gt=0)
    period: RecurringPeriod
    starts_on: date
    ends_on: date | None = None
    reminder_days_before: int | None = Field(default=None, ge=0, le=30)
    reminder_locale: ReminderLocale = "en"
    splits: list[RecurringSplitIn] | None = None


class RecurringUpdateIn(BaseModel):
    """All fields optional; the service layer applies only the fields
    explicitly present in the request body (`exclude_unset=True`).

    Deliberately NO `next_date`/`occurrence_index`/`last_reminded_for_date`
    field anywhere in this schema: a client cannot reset or otherwise
    alter the server-managed cursor by construction, not merely by
    convention (spec: "Editing notes leaves next_date untouched").
    `starts_on` is also absent — design D49 calls it an IMMUTABLE anchor;
    changing it after occurrences have begun generating would invalidate
    every already-computed `occurrence_index`."""

    account_id: uuid.UUID | None = None
    type: RecurringType | None = None
    amount: Decimal | None = None
    notes: str | None = None
    is_refund: bool | None = None
    is_subscription: bool | None = None
    repeat_every: int | None = Field(default=None, gt=0)
    period: RecurringPeriod | None = None
    ends_on: date | None = None
    reminder_days_before: int | None = Field(default=None, ge=0, le=30)
    reminder_locale: ReminderLocale | None = None
    splits: list[RecurringSplitIn] | None = None
