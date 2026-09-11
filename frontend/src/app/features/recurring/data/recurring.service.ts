import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** Design decision 8: income|expense only, never transfer (R2). */
export type RecurringType = 'income' | 'expense';
export type RecurringPeriod = 'day' | 'week' | 'month' | 'year';
export type ReminderLocale = 'en' | 'es';

/** One allocation line as returned on `RecurringOut` (design D55 —
 * mirrors `transaction_category_split`'s shape, own `id`). */
export interface RecurringSplit {
  id: string;
  category_id: string;
  amount: string;
}

/** One allocation line as SENT inline in a `POST`/`PATCH` request body
 * (`RecurringSplitIn` on the backend). */
export interface RecurringSplitInput {
  category_id: string;
  amount: string;
}

/** `GET/POST/GET-by-id/PATCH /api/recurring` response shape (design's
 * Interfaces/Contracts section, D19/D47/D49 — `next_date`/`occurrence_index`/
 * `last_reminded_for_date` are server-managed cursors, never client-set). */
export interface Recurring {
  id: string;
  workspace_id: string;
  account_id: string;
  type: RecurringType;
  amount: string;
  notes: string | null;
  is_refund: boolean;
  is_subscription: boolean;
  repeat_every: number;
  period: RecurringPeriod;
  starts_on: string;
  occurrence_index: number;
  next_date: string;
  ends_on: string | null;
  reminder_days_before: number | null;
  last_reminded_for_date: string | null;
  reminder_locale: ReminderLocale;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
  splits: RecurringSplit[];
}

/** `POST /api/recurring` request body (`RecurringCreateIn`) — no
 * `next_date` field exists here at all: the server initializes it from
 * `starts_on`. No `to_account_id`/second-amount/`checked` field exists
 * either (R2, R7 mirrored). */
export interface RecurringCreate {
  account_id: string;
  type: RecurringType;
  amount: string;
  notes?: string | null;
  is_refund?: boolean;
  is_subscription?: boolean;
  repeat_every: number;
  period: RecurringPeriod;
  starts_on: string;
  ends_on?: string | null;
  reminder_days_before?: number | null;
  reminder_locale?: ReminderLocale;
  splits?: RecurringSplitInput[];
}

/** `PATCH /api/recurring/{id}` request body (`RecurringUpdateIn`) — every
 * field optional; deliberately NO `starts_on` field at all (design D49:
 * `starts_on` is an immutable anchor once occurrences may have begun
 * generating). */
export interface RecurringUpdate {
  account_id?: string;
  type?: RecurringType;
  amount?: string;
  notes?: string | null;
  is_refund?: boolean;
  is_subscription?: boolean;
  repeat_every?: number;
  period?: RecurringPeriod;
  ends_on?: string | null;
  reminder_days_before?: number | null;
  reminder_locale?: ReminderLocale;
  splits?: RecurringSplitInput[];
}

/** `GET /api/recurring` query params — `is_subscription` drives the
 * Subscriptions route preset (design D56); `account_id` filters by
 * account. */
export interface RecurringFilters {
  account_id?: string;
  is_subscription?: boolean;
}

export const RECURRING_ENDPOINT = '/api/recurring';

/**
 * HTTP calls for the `recurring-transactions` capability (design's
 * Interfaces/Contracts table, D45-D56), mirroring `TransactionsService`'s
 * style: a `signal`-based cache of the last-fetched list, `withCredentials`
 * on every call, money kept as `string` end-to-end.
 *
 * Design D56: the Subscriptions view is `GET /api/recurring?is_subscription
 * =true` — there is deliberately NO second service, entity, or route
 * family for it; `RecurringListPage` supplies `is_subscription: true` in
 * its own filters when rendered under the `subscriptions` route.
 */
@Injectable({ providedIn: 'root' })
export class RecurringService {
  private readonly http = inject(HttpClient);

  private readonly recurringSignal = signal<Recurring[]>([]);
  readonly recurring = this.recurringSignal.asReadonly();

  /** `GET /api/recurring?is_subscription=&account_id=` — only defined
   * filters are sent as query params. */
  listRecurring(filters: RecurringFilters = {}): Observable<Recurring[]> {
    let params = new HttpParams();
    if (filters.account_id) params = params.set('account_id', filters.account_id);
    if (filters.is_subscription !== undefined) {
      params = params.set('is_subscription', String(filters.is_subscription));
    }

    return this.http
      .get<Recurring[]>(RECURRING_ENDPOINT, { params, withCredentials: true })
      .pipe(tap((recurring) => this.recurringSignal.set(recurring)));
  }

  /** `POST /api/recurring` — creates a recurrence; `next_date`/
   * `occurrence_index` are initialized server-side from `starts_on`. */
  createRecurring(body: RecurringCreate): Observable<Recurring> {
    return this.http.post<Recurring>(RECURRING_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/recurring/{id}` — 404 for any recurrence outside the
   * caller's visibility (design D18). */
  getRecurring(id: string): Observable<Recurring> {
    return this.http.get<Recurring>(`${RECURRING_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `PATCH /api/recurring/{id}` — never sends `starts_on` (see
   * `RecurringUpdate`'s doc comment); an optional whole-set `splits`
   * replacement. */
  updateRecurring(id: string, changes: RecurringUpdate): Observable<Recurring> {
    return this.http.patch<Recurring>(`${RECURRING_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/recurring/{id}`. */
  deleteRecurring(id: string): Observable<void> {
    return this.http.delete<void>(`${RECURRING_ENDPOINT}/${id}`, { withCredentials: true });
  }
}
