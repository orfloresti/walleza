import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { Transaction } from '../../transactions/data/transactions.service';

/** Design decision 8: income|expense only, never transfer (mirrors
 * `TransactionType`/`RecurringType`). */
export type TemplateType = 'income' | 'expense';

/** One allocation line as returned on `TemplateOut` (design D55 — mirrors
 * `transaction_category_split`'s shape, own `id`). */
export interface TemplateSplit {
  id: string;
  category_id: string;
  amount: string;
}

/** One allocation line as SENT inline in a `POST`/`PATCH` request body
 * (`TemplateSplitIn` on the backend) — no `id`, mirrors
 * `transactions.service.ts`'s `SplitInput` exactly. */
export interface TemplateSplitInput {
  category_id: string;
  amount: string;
}

/** `GET/POST/GET-by-id/PATCH /api/templates` response shape (design's
 * Interfaces/Contracts section, D19 — `amount` is a Decimal serialized as
 * a JSON STRING, never a number, kept as `string` end-to-end). A template
 * is a reusable SHAPE — no `occurred_on`/`checked`/`is_refund` field
 * exists anywhere on it (R7). */
export interface Template {
  id: string;
  workspace_id: string;
  account_id: string;
  name: string;
  position: number;
  type: TemplateType;
  amount: string;
  notes: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
  splits: TemplateSplit[];
}

/** `POST /api/templates` request body (`TemplateCreateIn`). */
export interface TemplateCreate {
  name: string;
  account_id: string;
  type: TemplateType;
  amount: string;
  notes?: string | null;
  position?: number;
  splits?: TemplateSplitInput[];
}

/** `PATCH /api/templates/{id}` request body (`TemplateUpdateIn`) — every
 * field optional; only fields present are applied server-side
 * (`exclude_unset=True`), mirroring `TransactionUpdate`. */
export interface TemplateUpdate {
  name?: string;
  account_id?: string;
  type?: TemplateType;
  amount?: string;
  notes?: string | null;
  position?: number;
  splits?: TemplateSplitInput[];
}

/** `POST /api/templates/{id}/apply` request body (`TemplateApplyIn`,
 * design D56) — the ONLY accepted override is `occurred_on`, defaulting
 * to today when omitted. The template row is never modified by an apply. */
export interface TemplateApplyBody {
  occurred_on?: string;
}

export const TEMPLATES_ENDPOINT = '/api/templates';

/**
 * HTTP calls for the `transaction-templates` capability (design's
 * Interfaces/Contracts table, D56), mirroring `TransactionsService`'s
 * style: a `signal`-based cache of the last-fetched list, `withCredentials`
 * on every call, money kept as `string` end-to-end.
 *
 * The server already scopes every response to what the caller may see
 * (`visible_templates(scope, account_id)`) — this service and its
 * consumers never re-filter or re-derive visibility client-side, they
 * only render what the API returned.
 */
@Injectable({ providedIn: 'root' })
export class TemplatesService {
  private readonly http = inject(HttpClient);

  private readonly templatesSignal = signal<Template[]>([]);
  readonly templates = this.templatesSignal.asReadonly();

  /** `GET /api/templates?account_id=` — optionally filtered by account. */
  listTemplates(accountId?: string): Observable<Template[]> {
    let params = new HttpParams();
    if (accountId) params = params.set('account_id', accountId);

    return this.http
      .get<Template[]>(TEMPLATES_ENDPOINT, { params, withCredentials: true })
      .pipe(tap((templates) => this.templatesSignal.set(templates)));
  }

  /** `POST /api/templates` — creates a reusable transaction shape. */
  createTemplate(body: TemplateCreate): Observable<Template> {
    return this.http.post<Template>(TEMPLATES_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/templates/{id}` — 404 for any template outside the
   * caller's visibility (design D18). */
  getTemplate(id: string): Observable<Template> {
    return this.http.get<Template>(`${TEMPLATES_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `PATCH /api/templates/{id}` — the one mutation path for the shape's
   * fields, including an optional whole-set `splits` replacement. */
  updateTemplate(id: string, changes: TemplateUpdate): Observable<Template> {
    return this.http.patch<Template>(`${TEMPLATES_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/templates/{id}`. */
  deleteTemplate(id: string): Observable<void> {
    return this.http.delete<void>(`${TEMPLATES_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `POST /api/templates/{id}/apply` — creates a real `Transaction` from
   * the template (design D56); the template row itself is left byte-
   * identically unchanged and reusable immediately. `body` is optional —
   * omitting it (or `occurred_on`) applies against today's date. */
  applyTemplate(id: string, body: TemplateApplyBody = {}): Observable<Transaction> {
    return this.http.post<Transaction>(`${TEMPLATES_ENDPOINT}/${id}/apply`, body, {
      withCredentials: true,
    });
  }
}
