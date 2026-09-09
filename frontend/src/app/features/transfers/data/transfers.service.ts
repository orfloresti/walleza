import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** `GET/POST/GET-by-id /api/transfers` response shape (design's
 * Interfaces/Contracts section, `TransferOut`, D19 — both amounts are a
 * Decimal serialized as a JSON STRING, never a number, kept as `string`
 * end-to-end here exactly like `TransactionsService`/`AccountsService`).
 * `to_amount` IS present on the response — it is server-derived and
 * always rendered, just never sent by the client on create (D40/D44). */
export interface Transfer {
  id: string;
  workspace_id: string;
  from_account_id: string;
  to_account_id: string;
  from_amount: string;
  to_amount: string;
  occurred_on: string;
  notes: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

/** `POST /api/transfers` request body (`TransferCreateIn`) — design D40/
 * D44: deliberately NO `to_amount` field. The server always derives it
 * (`_derive_to_amount`); this type having no such field is how
 * "server-derived, never client-supplied" is enforced as a shape
 * guarantee, not a runtime check. No `category_id`/`splits` either
 * (design T5 — a transfer carries no category association). */
export interface TransferCreate {
  from_account_id: string;
  to_account_id: string;
  from_amount: string;
  occurred_on: string;
  notes?: string | null;
}

/** `GET /api/transfers` query params (design's `visible_transfers`
 * filter set: account — matches EITHER `from_account_id` or
 * `to_account_id` — and date range). */
export interface TransferFilters {
  account_id?: string;
  date_from?: string;
  date_to?: string;
}

export const TRANSFERS_ENDPOINT = '/api/transfers';

/**
 * HTTP calls for the `transfer-management`/`account-transfers`
 * capability (design's Interfaces/Contracts table), mirroring
 * `TransactionsService`'s style: a `signal`-based cache of the
 * last-fetched list, `withCredentials` on every call, money kept as
 * `string` end-to-end.
 *
 * The server already scopes every response to what the caller may see
 * (`visible_transfers(scope, ...)`, design D38's double-INNER-JOIN) —
 * this service and its consumers never re-filter or re-derive visibility
 * client-side, they only render what the API returned.
 *
 * There is deliberately NO `updateTransfer` method — design D43:
 * absence at every layer (route, service function, schema, client
 * method, frontend route) is how "no update endpoint exists" is proved,
 * not just documented.
 */
@Injectable({ providedIn: 'root' })
export class TransfersService {
  private readonly http = inject(HttpClient);

  private readonly transfersSignal = signal<Transfer[]>([]);
  readonly transfers = this.transfersSignal.asReadonly();

  /** `GET /api/transfers?account_id&date_from&date_to` — filterable by
   * account (matches either side of the transfer) and/or date range.
   * Only defined filters are sent as query params. */
  listTransfers(filters: TransferFilters = {}): Observable<Transfer[]> {
    let params = new HttpParams();
    if (filters.account_id) params = params.set('account_id', filters.account_id);
    if (filters.date_from) params = params.set('date_from', filters.date_from);
    if (filters.date_to) params = params.set('date_to', filters.date_to);

    return this.http
      .get<Transfer[]>(TRANSFERS_ENDPOINT, { params, withCredentials: true })
      .pipe(tap((transfers) => this.transfersSignal.set(transfers)));
  }

  /** `POST /api/transfers` — creates a transfer between two of the
   * caller's visible accounts. `to_amount` is never part of `body`
   * (see `TransferCreate`'s doc comment) — the server derives and
   * returns it on the response. */
  createTransfer(body: TransferCreate): Observable<Transfer> {
    return this.http.post<Transfer>(TRANSFERS_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/transfers/{id}` — 404 for any transfer outside the
   * caller's visibility (design D41: a whole resource addressed by id
   * outside `visible_transfers` is 404, not 422). */
  getTransfer(id: string): Observable<Transfer> {
    return this.http.get<Transfer>(`${TRANSFERS_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `DELETE /api/transfers/{id}` — single-row removal; there is no
   * paired row and no update endpoint (design D43). */
  deleteTransfer(id: string): Observable<void> {
    return this.http.delete<void>(`${TRANSFERS_ENDPOINT}/${id}`, { withCredentials: true });
  }
}
