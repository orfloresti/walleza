/**
 * `RecurringService` HTTP contract tests (Phase 4 PR5, task 5.5), same
 * `HttpTestingController` pattern `transfers.service.spec.ts` established
 * — no live backend, only the real `HttpClient` against a mock backend,
 * proving each call hits the exact path/method/body/query-params
 * `app/recurring/{router,schemas}.py` defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { RecurringService } from './recurring.service';

const RECURRING_RESPONSE = {
  id: 'recurring-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  type: 'expense',
  amount: '9.99',
  notes: null,
  is_refund: false,
  is_subscription: true,
  repeat_every: 1,
  period: 'month',
  starts_on: '2026-01-01',
  occurrence_index: 0,
  next_date: '2026-01-01',
  ends_on: null,
  reminder_days_before: null,
  last_reminded_for_date: null,
  reminder_locale: 'en',
  created_by_user_id: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  splits: [],
};

describe('RecurringService', () => {
  let service: RecurringService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(RecurringService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/recurring with no filters lists recurring transactions and caches them', async () => {
    const promise = firstValueFrom(service.listRecurring());

    const req = httpMock.expectOne((r) => r.url === '/api/recurring');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.params.keys().length).toBe(0);
    req.flush([RECURRING_RESPONSE]);

    const recurring = await promise;
    expect(recurring).toEqual([RECURRING_RESPONSE]);
    expect(service.recurring()).toEqual([RECURRING_RESPONSE]);
  });

  it('GET /api/recurring?is_subscription=true sends the Subscriptions preset as a query param (task focus)', async () => {
    const promise = firstValueFrom(service.listRecurring({ is_subscription: true }));

    const req = httpMock.expectOne((r) => r.url === '/api/recurring');
    expect(req.request.params.get('is_subscription')).toBe('true');
    req.flush([RECURRING_RESPONSE]);

    await promise;
  });

  it('GET /api/recurring?account_id filters by account when provided, omitting is_subscription entirely', async () => {
    const promise = firstValueFrom(service.listRecurring({ account_id: 'acc-1' }));

    const req = httpMock.expectOne((r) => r.url === '/api/recurring');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    expect(req.request.params.has('is_subscription')).toBe(false);
    req.flush([]);

    await promise;
  });

  it('POST /api/recurring creates a recurrence with the exact body shape, never sending next_date (task focus)', async () => {
    const promise = firstValueFrom(
      service.createRecurring({
        account_id: 'acc-1',
        type: 'expense',
        amount: '9.99',
        notes: null,
        is_refund: false,
        is_subscription: true,
        repeat_every: 1,
        period: 'month',
        starts_on: '2026-01-01',
        ends_on: null,
        reminder_days_before: null,
        reminder_locale: 'en',
      }),
    );

    const req = httpMock.expectOne('/api/recurring');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '9.99',
      notes: null,
      is_refund: false,
      is_subscription: true,
      repeat_every: 1,
      period: 'month',
      starts_on: '2026-01-01',
      ends_on: null,
      reminder_days_before: null,
      reminder_locale: 'en',
    });
    expect('next_date' in req.request.body).toBe(false);
    req.flush(RECURRING_RESPONSE);

    const recurring = await promise;
    expect(recurring.id).toBe('recurring-1');
  });

  it('GET /api/recurring/{id} fetches a single recurrence', async () => {
    const promise = firstValueFrom(service.getRecurring('recurring-1'));

    const req = httpMock.expectOne('/api/recurring/recurring-1');
    expect(req.request.method).toBe('GET');
    req.flush(RECURRING_RESPONSE);

    const recurring = await promise;
    expect(recurring.id).toBe('recurring-1');
  });

  it('PATCH /api/recurring/{id} updates fields and never carries a starts_on key (design D49)', async () => {
    const promise = firstValueFrom(service.updateRecurring('recurring-1', { notes: 'Updated' }));

    const req = httpMock.expectOne('/api/recurring/recurring-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ notes: 'Updated' });
    expect('starts_on' in req.request.body).toBe(false);
    req.flush({ ...RECURRING_RESPONSE, notes: 'Updated' });

    const recurring = await promise;
    expect(recurring.notes).toBe('Updated');
  });

  it('DELETE /api/recurring/{id} deletes a recurrence', async () => {
    const promise = firstValueFrom(service.deleteRecurring('recurring-1'));

    const req = httpMock.expectOne('/api/recurring/recurring-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });
});
