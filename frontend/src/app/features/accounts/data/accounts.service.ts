import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/**
 * `GET/POST/GET-by-id/PATCH /api/accounts` response shape (design D19 —
 * `exchange_rate`/`initial_funds` are Python `Decimal` serialized as JSON
 * STRINGS, never numbers, to avoid a binary-float round trip silently
 * losing precision). Kept as `string` end-to-end here: this service never
 * parses them into a JS `number`, only ever forwards the exact value the
 * backend returned (read) or the exact value the form field holds
 * (write-back).
 */
export interface Account {
  id: string;
  workspace_id: string;
  owner_user_id: string | null;
  name: string;
  currency: string;
  exchange_rate: string;
  initial_funds: string;
  is_personal: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
}

/** `POST /api/accounts` request body (`AccountCreateIn`). `owner_user_id`
 * is deliberately not a field — the backend derives ownership from the
 * authenticated scope, never from the request body. */
export interface AccountCreate {
  name: string;
  currency: string;
  exchange_rate: string;
  initial_funds: string;
  is_personal: boolean;
}

/** `PATCH /api/accounts/{id}` request body (`AccountUpdateIn`) — every
 * field optional; only fields present are applied server-side
 * (`exclude_unset=True`). Archiving is `{ archived: true }`, not a
 * DELETE — there is no DELETE route (design's Interfaces/Contracts
 * table, decision 6). */
export interface AccountUpdate {
  name?: string;
  currency?: string;
  exchange_rate?: string;
  initial_funds?: string;
  archived?: boolean;
}

/** `GET /api/workspace/summary` response shape (design D16). */
export interface CurrencyTotal {
  currency: string;
  total: string;
}

export interface WorkspaceSummary {
  by_currency: CurrencyTotal[];
  grand_total: string;
}

export const ACCOUNTS_ENDPOINT = '/api/accounts';
export const WORKSPACE_SUMMARY_ENDPOINT = '/api/workspace/summary';

/**
 * HTTP calls for the `account-management`/`account-visibility`
 * capabilities (design's Interfaces/Contracts table), mirroring
 * `WorkspaceService`'s style: a `signal`-based cache of the
 * last-fetched list, `withCredentials` on every call (design D8).
 *
 * The server already scopes every response to what the caller may see
 * (`visible_accounts(scope)`, design D14/D15) — this service and its
 * consumers never re-filter or re-derive visibility client-side; they
 * only render what the API returned.
 */
@Injectable({ providedIn: 'root' })
export class AccountsService {
  private readonly http = inject(HttpClient);

  private readonly accountsSignal = signal<Account[]>([]);
  readonly accounts = this.accountsSignal.asReadonly();

  /** `GET /api/accounts?archived=` — defaults to the active (non-archived)
   * list, matching the backend's own default (design decision 6). */
  listAccounts(archived = false): Observable<Account[]> {
    return this.http
      .get<Account[]>(ACCOUNTS_ENDPOINT, {
        params: { archived },
        withCredentials: true,
      })
      .pipe(tap((accounts) => this.accountsSignal.set(accounts)));
  }

  /** `POST /api/accounts` — creates a shared or personal account in the
   * caller's workspace. */
  createAccount(body: AccountCreate): Observable<Account> {
    return this.http.post<Account>(ACCOUNTS_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/accounts/{id}` — 404 for any account outside the caller's
   * visibility (design D18: a 403 would confirm the row exists). */
  getAccount(id: string): Observable<Account> {
    return this.http.get<Account>(`${ACCOUNTS_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `PATCH /api/accounts/{id}` — the one mutation path for name,
   * currency, exchange_rate, initial_funds, and `archived`. */
  updateAccount(id: string, changes: AccountUpdate): Observable<Account> {
    return this.http.patch<Account>(`${ACCOUNTS_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** Archiving is `PATCH { archived: true }` — there is no DELETE route
   * for accounts (design's Interfaces/Contracts table, decision 6). */
  archiveAccount(id: string): Observable<Account> {
    return this.updateAccount(id, { archived: true });
  }

  /** `GET /api/workspace/summary` — per-currency totals plus a converted
   * grand total, aggregated server-side over the identical `Select` the
   * default account list uses (design D16). The frontend renders these
   * numbers; it never computes them. */
  getSummary(): Observable<WorkspaceSummary> {
    return this.http.get<WorkspaceSummary>(WORKSPACE_SUMMARY_ENDPOINT, {
      withCredentials: true,
    });
  }
}
