/**
 * `TransfersService` HTTP contract tests (Phase 3 PR2, task 2.6), same
 * `HttpTestingController` pattern `transactions.service.spec.ts`
 * established — no live backend, only the real `HttpClient` against a
 * mock backend, proving each call hits the exact path/method/body/
 * query-params `app/transfers/{router,schemas}.py` defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { TransfersService } from './transfers.service';

const TRANSFER_RESPONSE = {
  id: 'transfer-1',
  workspace_id: 'ws-1',
  from_account_id: 'acc-1',
  to_account_id: 'acc-2',
  from_amount: '100.00',
  to_amount: '50.00',
  occurred_on: '2026-01-15',
  notes: 'Moving savings',
  created_by_user_id: 'user-1',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z',
};

describe('TransfersService', () => {
  let service: TransfersService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TransfersService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/transfers with no filters lists transfers and caches them', async () => {
    const promise = firstValueFrom(service.listTransfers());

    const req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.params.keys().length).toBe(0);
    req.flush([TRANSFER_RESPONSE]);

    const transfers = await promise;
    expect(transfers).toEqual([TRANSFER_RESPONSE]);
    expect(service.transfers()).toEqual([TRANSFER_RESPONSE]);
  });

  it('GET /api/transfers sends every provided filter as a query param (task focus)', async () => {
    const promise = firstValueFrom(
      service.listTransfers({
        account_id: 'acc-1',
        date_from: '2026-01-01',
        date_to: '2026-01-31',
      }),
    );

    const req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    req.flush([]);

    await promise;
  });

  it('GET /api/transfers omits filters that are not provided', async () => {
    const promise = firstValueFrom(service.listTransfers({ account_id: 'acc-1' }));

    const req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    expect(req.request.params.has('date_from')).toBe(false);
    expect(req.request.params.has('date_to')).toBe(false);
    req.flush([]);

    await promise;
  });

  it('POST /api/transfers creates a transfer with the exact body shape and NEVER sends to_amount (task focus)', async () => {
    const promise = firstValueFrom(
      service.createTransfer({
        from_account_id: 'acc-1',
        to_account_id: 'acc-2',
        from_amount: '100.00',
        occurred_on: '2026-01-15',
        notes: 'Moving savings',
      }),
    );

    const req = httpMock.expectOne('/api/transfers');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      from_account_id: 'acc-1',
      to_account_id: 'acc-2',
      from_amount: '100.00',
      occurred_on: '2026-01-15',
      notes: 'Moving savings',
    });
    // Money travels as a string on the wire (design D19) — never coerced
    // to a JS number anywhere in this round trip.
    expect(typeof req.request.body.from_amount).toBe('string');
    // The server derives to_amount (D40) — the request body must never
    // carry it, matching the backend's silently-ignored-if-present rule
    // by simply never sending the key at all.
    expect(req.request.body.to_amount).toBeUndefined();
    expect('to_amount' in req.request.body).toBe(false);
    req.flush(TRANSFER_RESPONSE);

    const transfer = await promise;
    expect(transfer.to_amount).toBe('50.00');
  });

  it('GET /api/transfers/{id} fetches a single transfer', async () => {
    const promise = firstValueFrom(service.getTransfer('transfer-1'));

    const req = httpMock.expectOne('/api/transfers/transfer-1');
    expect(req.request.method).toBe('GET');
    req.flush(TRANSFER_RESPONSE);

    const transfer = await promise;
    expect(transfer.id).toBe('transfer-1');
  });

  it('DELETE /api/transfers/{id} deletes a transfer', async () => {
    const promise = firstValueFrom(service.deleteTransfer('transfer-1'));

    const req = httpMock.expectOne('/api/transfers/transfer-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });

  it('exposes no updateTransfer method (design D43 — no update endpoint exists at any layer)', () => {
    expect((service as unknown as Record<string, unknown>)['updateTransfer']).toBeUndefined();
  });
});
