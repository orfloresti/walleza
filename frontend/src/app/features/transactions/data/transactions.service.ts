import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** Design decision 8: income|expense only, never transfer (P3's entity). */
export type TransactionType = 'income' | 'expense';

/** One allocation line as returned on `TransactionOut` (has its own `id`,
 * design D21 — an empty list means "uncategorized", a legal state). */
export interface Split {
  id: string;
  category_id: string;
  amount: string;
}

/** One allocation line as SENT inline in a `POST`/`PATCH` request body
 * (`SplitIn` on the backend, design D21/D33) — no `id`: the server
 * assigns one on write. Amount travels as the raw string the split
 * editor's input field holds, never parsed into a JS number (design
 * D19), and the server is the sole authority on whether the set of
 * lines sums exactly to the transaction's own amount (design D22) — this
 * type carries no validation of its own. */
export interface SplitInput {
  category_id: string;
  amount: string;
}

/** `GET/POST/GET-by-id/PATCH /api/transactions` response shape (design's
 * Interfaces/Contracts section, design D19 — `amount` is a Decimal
 * serialized as a JSON STRING, never a number, kept as `string`
 * end-to-end here exactly like `AccountsService`'s money fields). */
export interface Transaction {
  id: string;
  workspace_id: string;
  account_id: string;
  type: TransactionType;
  amount: string;
  occurred_on: string;
  notes: string | null;
  is_refund: boolean;
  checked: boolean;
  photo_content_type: string | null;
  photo_uploaded_at: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  splits: Split[];
}

/** `POST /api/transactions` request body (`TransactionCreateIn`) —
 * account, amount, date, notes, type, is_refund, checked, plus an
 * OPTIONAL `splits` array (design D21/PR6b, task 8.1). Omitting `splits`
 * entirely (the key itself, not an empty array) is legal and means zero
 * lines, "uncategorized" — `TransactionFormPage.save()` only assigns
 * this key when the split editor holds at least one row, so the basic
 * (no-split) case sends exactly the same wire body PR6 already shipped
 * and already has passing tests for. */
export interface TransactionCreate {
  account_id: string;
  type: TransactionType;
  amount: string;
  occurred_on: string;
  notes?: string | null;
  is_refund?: boolean;
  checked?: boolean;
  splits?: SplitInput[];
}

/** `PATCH /api/transactions/{id}` request body (`TransactionUpdateIn`) —
 * every field optional; only fields present are applied server-side
 * (`exclude_unset=True`). An OPTIONAL `splits` array (design D22/PR6b):
 * when present in the request body AT ALL (including an explicit empty
 * array), it REPLACES the whole existing split set; when the key is
 * absent, existing split lines are left untouched server-side unless
 * `amount` also changes, in which case the server re-validates the
 * untouched splits still sum to the new amount and rejects the update if
 * they no longer do — surfaced as a 422, the same as any other
 * validation failure (design D33). */
export interface TransactionUpdate {
  account_id?: string;
  type?: TransactionType;
  amount?: string;
  occurred_on?: string;
  notes?: string | null;
  is_refund?: boolean;
  checked?: boolean;
  splits?: SplitInput[];
}

/** `GET /api/transactions` query params (design's `visible_transactions`
 * filter set: account, category, date range, type). */
export interface TransactionFilters {
  account_id?: string;
  category_id?: string;
  date_from?: string;
  date_to?: string;
  type?: TransactionType;
}

/** `POST /api/transactions/{id}/photo/upload-url` response (design D24
 * step ②/D25 — `PhotoUploadUrlOut`): the exact `generate_presigned_post`
 * payload (`url` + `fields`, boto3's own dict shape, passed through
 * verbatim by `app/storage.py`'s `presigned_upload`) plus `expires_at`/
 * `max_bytes`/`content_type`. `fields` is a flat string-keyed object —
 * every one of ITS entries must be appended to the `FormData` posted
 * directly to `url` BEFORE the actual file field (S3's own documented
 * presigned-POST requirement; `ui/receipt-upload` is the sole consumer
 * of this shape). */
export interface PhotoUploadUrlOut {
  url: string;
  fields: Record<string, string>;
  expires_at: string;
  max_bytes: number;
  content_type: string;
}

/** `PUT /api/transactions/{id}/photo` response (design D24 step ④ —
 * `PhotoConfirmOut`). */
export interface PhotoConfirmOut {
  photo_content_type: string;
  photo_uploaded_at: string;
}

/** `GET /api/transactions/{id}/photo` response (design D26 —
 * `PhotoDownloadUrlOut`). */
export interface PhotoDownloadUrlOut {
  url: string;
  expires_at: string;
}

export const TRANSACTIONS_ENDPOINT = '/api/transactions';

/**
 * HTTP calls for the `transaction-management`/`transaction-visibility`
 * capabilities (design's Interfaces/Contracts table), mirroring
 * `AccountsService`'s style: a `signal`-based cache of the last-fetched
 * list, `withCredentials` on every call (design D8), money kept as
 * `string` end-to-end.
 *
 * The server already scopes every response to what the caller may see
 * (`visible_transactions(scope, ...)`, design D30 — inherited entirely
 * from the account's own visibility) — this service and its consumers
 * never re-filter or re-derive visibility client-side, they only render
 * what the API returned.
 *
 * Photo/attachment endpoints (`/photo/upload-url`, `/photo`) were added in
 * PR6b — `ui/receipt-upload` is their sole consumer, driving design D24's
 * steps ②/③/④ (request the presigned POST, upload directly to S3, then
 * confirm) only after a transaction id already exists from step ①.
 */
@Injectable({ providedIn: 'root' })
export class TransactionsService {
  private readonly http = inject(HttpClient);

  private readonly transactionsSignal = signal<Transaction[]>([]);
  readonly transactions = this.transactionsSignal.asReadonly();

  /** `GET /api/transactions?account_id&category_id&date_from&date_to&type`
   * — the workspace-wide feed, filterable by any combination of the
   * above (design's Filtered Workspace Transaction Feed requirement).
   * Only defined filters are sent as query params. */
  listTransactions(filters: TransactionFilters = {}): Observable<Transaction[]> {
    let params = new HttpParams();
    if (filters.account_id) params = params.set('account_id', filters.account_id);
    if (filters.category_id) params = params.set('category_id', filters.category_id);
    if (filters.date_from) params = params.set('date_from', filters.date_from);
    if (filters.date_to) params = params.set('date_to', filters.date_to);
    if (filters.type) params = params.set('type', filters.type);

    return this.http
      .get<Transaction[]>(TRANSACTIONS_ENDPOINT, { params, withCredentials: true })
      .pipe(tap((transactions) => this.transactionsSignal.set(transactions)));
  }

  /** `POST /api/transactions` — creates a manual income/expense
   * transaction. This PR sends the BASIC-case body only (no `splits`,
   * no photo) — design D24's sequential save pipeline's step ① only;
   * PR6b appends the conditional photo steps on top of this same call. */
  createTransaction(body: TransactionCreate): Observable<Transaction> {
    return this.http.post<Transaction>(TRANSACTIONS_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/transactions/{id}` — 404 for any transaction outside the
   * caller's visibility (design D18: a 403 would confirm the row
   * exists). */
  getTransaction(id: string): Observable<Transaction> {
    return this.http.get<Transaction>(`${TRANSACTIONS_ENDPOINT}/${id}`, {
      withCredentials: true,
    });
  }

  /** `PATCH /api/transactions/{id}` — updates the BASIC-case fields;
   * never sends `splits` from this PR's edit form (see `TransactionUpdate`
   * doc comment). */
  updateTransaction(id: string, changes: TransactionUpdate): Observable<Transaction> {
    return this.http.patch<Transaction>(`${TRANSACTIONS_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/transactions/{id}` — also removes any attached photo,
   * best-effort, server-side (design D27); this service issues no
   * separate photo-cleanup call. */
  deleteTransaction(id: string): Observable<void> {
    return this.http.delete<void>(`${TRANSACTIONS_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `POST /api/transactions/{id}/photo/upload-url` — design D24 step ②:
   * authorization (`visible_transactions`) is checked server-side BEFORE
   * any presigned URL is minted; this call itself carries the caller's
   * session cookie (`withCredentials`) exactly like every other call on
   * this service, since it hits THIS app's own backend, not S3. */
  requestPhotoUploadUrl(transactionId: string, contentType: string): Observable<PhotoUploadUrlOut> {
    return this.http.post<PhotoUploadUrlOut>(
      `${TRANSACTIONS_ENDPOINT}/${transactionId}/photo/upload-url`,
      { content_type: contentType },
      { withCredentials: true },
    );
  }

  /** `PUT /api/transactions/{id}/photo` — design D24 step ④: confirms the
   * upload actually landed (`app.storage.object_exists`) before marking
   * `photo_uploaded_at`; 409 when it did not. Called only after step ③'s
   * direct-to-S3 POST has itself succeeded. */
  confirmPhotoUpload(transactionId: string, contentType: string): Observable<PhotoConfirmOut> {
    return this.http.put<PhotoConfirmOut>(
      `${TRANSACTIONS_ENDPOINT}/${transactionId}/photo`,
      { content_type: contentType },
      { withCredentials: true },
    );
  }

  /** `GET /api/transactions/{id}/photo` — design D26: a presigned GET,
   * subject to the same visibility rule as every other transaction read. */
  getPhotoDownloadUrl(transactionId: string): Observable<PhotoDownloadUrlOut> {
    return this.http.get<PhotoDownloadUrlOut>(`${TRANSACTIONS_ENDPOINT}/${transactionId}/photo`, {
      withCredentials: true,
    });
  }
}
