import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** `progress.status` classification (design D75: on_track < 80%,
 * near_limit 80-99.99%, over_budget >= 100%). */
export type BudgetStatus = 'on_track' | 'near_limit' | 'over_budget';

/** `progress` field on `BudgetWithProgressOut` (`backend/app/budgets/
 * schemas.py`'s `BudgetProgressOut`) — never persisted, computed live on
 * every read (design D71-D78). Money kept as `string` end-to-end (design
 * D19), `percent` is an unclamped `float`. */
export interface BudgetProgress {
  limit: string;
  spent: string;
  remaining: string;
  percent: number;
  status: BudgetStatus;
  period_start: string;
  period_end: string;
}

/** `GET/POST/GET-by-id/PATCH /api/budgets` response shape
 * (`BudgetWithProgressOut`) — every budget route returns this shape, there
 * is no separate bare-CRUD response (design's Interfaces/Contracts
 * table). */
export interface Budget {
  id: string;
  workspace_id: string;
  category_id: string;
  account_id: string | null;
  name: string | null;
  amount: string;
  currency: string;
  created_at: string;
  updated_at: string;
  progress: BudgetProgress;
}

/** `POST /api/budgets` request body (`BudgetCreateIn`) — `category_id`
 * required, `account_id` optional (category-only budget when omitted). */
export interface BudgetCreate {
  category_id: string;
  account_id?: string | null;
  name?: string | null;
  amount: string;
  currency: string;
}

/** `PATCH /api/budgets/{id}` request body (`BudgetUpdateIn`) — every field
 * optional; only fields present are applied server-side
 * (`exclude_unset=True`). */
export interface BudgetUpdate {
  category_id?: string;
  account_id?: string | null;
  name?: string | null;
  amount?: string;
  currency?: string;
}

export const BUDGETS_ENDPOINT = '/api/budgets';

/**
 * HTTP calls for the `budget-management`/`budget-progress` capabilities
 * (design's Interfaces/Contracts table), mirroring `CategoriesService`'s
 * style: a `signal`-based cache of the last-fetched list, `withCredentials`
 * on every call (design D8).
 *
 * The server already scopes every response to the caller's own workspace
 * (`visible_budgets(scope)`, design D70) and computes `progress` live —
 * this service and its consumers never re-filter, re-derive visibility, or
 * recompute progress client-side; they only render what the API returned.
 */
@Injectable({ providedIn: 'root' })
export class BudgetsService {
  private readonly http = inject(HttpClient);

  private readonly budgetsSignal = signal<Budget[]>([]);
  readonly budgets = this.budgetsSignal.asReadonly();

  /** `GET /api/budgets` — every visible budget, each with its current-month
   * progress computed server-side. */
  listBudgets(): Observable<Budget[]> {
    return this.http
      .get<Budget[]>(BUDGETS_ENDPOINT, { withCredentials: true })
      .pipe(tap((budgets) => this.budgetsSignal.set(budgets)));
  }

  /** `POST /api/budgets` — creates a category-only or account-scoped
   * budget. */
  createBudget(body: BudgetCreate): Observable<Budget> {
    return this.http.post<Budget>(BUDGETS_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/budgets/{id}` — 404 for a budget outside the caller's
   * workspace (design D18: a 403 would confirm the row exists). */
  getBudget(id: string): Observable<Budget> {
    return this.http.get<Budget>(`${BUDGETS_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `PATCH /api/budgets/{id}` — the one mutation path for
   * category_id/account_id/name/amount/currency. */
  updateBudget(id: string, changes: BudgetUpdate): Observable<Budget> {
    return this.http.patch<Budget>(`${BUDGETS_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/budgets/{id}`. */
  deleteBudget(id: string): Observable<void> {
    return this.http.delete<void>(`${BUDGETS_ENDPOINT}/${id}`, { withCredentials: true });
  }
}
