/**
 * `AccountsService` HTTP contract tests (Phase 1 PR4b, task 8.4), same
 * `HttpTestingController` pattern `workspace.service.spec.ts` established
 * in PR4 — no live backend, only the real `HttpClient` against a mock
 * backend, proving each call hits the exact path/method/body the
 * backend's `app/accounts/{router,schemas}.py` (Phase 1 PR3) and
 * `app/workspace/router.py`'s `/summary` route define.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AccountsService } from './accounts.service';

const ACCOUNT_RESPONSE = {
  id: 'acc-1',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Checking',
  currency: 'USD',
  exchange_rate: '1.00000000',
  initial_funds: '100.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('AccountsService', () => {
  let service: AccountsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AccountsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/accounts?archived=false lists the active accounts by default and caches them in the signal', async () => {
    const promise = firstValueFrom(service.listAccounts());

    const req = httpMock.expectOne((r) => r.url === '/api/accounts');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('archived')).toBe('false');
    expect(req.request.withCredentials).toBe(true);
    req.flush([ACCOUNT_RESPONSE]);

    const accounts = await promise;
    expect(accounts).toEqual([ACCOUNT_RESPONSE]);
    expect(service.accounts()).toEqual([ACCOUNT_RESPONSE]);
  });

  it('GET /api/accounts?archived=true lists archived accounts when requested', async () => {
    const promise = firstValueFrom(service.listAccounts(true));

    const req = httpMock.expectOne((r) => r.url === '/api/accounts');
    expect(req.request.params.get('archived')).toBe('true');
    req.flush([{ ...ACCOUNT_RESPONSE, archived: true }]);

    await promise;
  });

  it('POST /api/accounts creates an account with the exact body shape (task focus)', async () => {
    const promise = firstValueFrom(
      service.createAccount({
        name: 'Savings',
        currency: 'USD',
        exchange_rate: '1',
        initial_funds: '250.50',
        is_personal: true,
      }),
    );

    const req = httpMock.expectOne('/api/accounts');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Savings',
      currency: 'USD',
      exchange_rate: '1',
      initial_funds: '250.50',
      is_personal: true,
    });
    // Money fields travel as strings on the wire (design D19) — never
    // silently coerced to a JS number anywhere in this round trip.
    expect(typeof req.request.body.exchange_rate).toBe('string');
    expect(typeof req.request.body.initial_funds).toBe('string');
    req.flush({ ...ACCOUNT_RESPONSE, name: 'Savings', is_personal: true });

    const account = await promise;
    expect(account.name).toBe('Savings');
  });

  it('GET /api/accounts/{id} fetches a single account', async () => {
    const promise = firstValueFrom(service.getAccount('acc-1'));

    const req = httpMock.expectOne('/api/accounts/acc-1');
    expect(req.request.method).toBe('GET');
    req.flush(ACCOUNT_RESPONSE);

    const account = await promise;
    expect(account.id).toBe('acc-1');
  });

  it('archiveAccount calls PATCH /api/accounts/{id} with { archived: true } (task focus — no DELETE route exists)', async () => {
    const promise = firstValueFrom(service.archiveAccount('acc-1'));

    const req = httpMock.expectOne('/api/accounts/acc-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ archived: true });
    req.flush({ ...ACCOUNT_RESPONSE, archived: true });

    const account = await promise;
    expect(account.archived).toBe(true);
  });

  it('GET /api/workspace/summary resolves per-currency totals and the grand total', async () => {
    const promise = firstValueFrom(service.getSummary());

    const req = httpMock.expectOne('/api/workspace/summary');
    expect(req.request.method).toBe('GET');
    req.flush({
      by_currency: [
        { currency: 'USD', total: '350.50' },
        { currency: 'EUR', total: '10.00' },
      ],
      grand_total: '360.50',
    });

    const summary = await promise;
    expect(summary.by_currency).toEqual([
      { currency: 'USD', total: '350.50' },
      { currency: 'EUR', total: '10.00' },
    ]);
    expect(summary.grand_total).toBe('360.50');
  });
});
