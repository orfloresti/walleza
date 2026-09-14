/**
 * `BudgetsService` HTTP contract tests, same `HttpTestingController`
 * pattern `recurring.service.spec.ts` established — no live backend, only
 * the real `HttpClient` against a mock backend, proving each call hits the
 * exact path/method/body `app/budgets/{router,schemas}.py` defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { BudgetsService } from './budgets.service';

const BUDGET_RESPONSE = {
  id: 'budget-1',
  workspace_id: 'ws-1',
  category_id: 'cat-1',
  account_id: null,
  name: null,
  amount: '500.00',
  currency: 'USD',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  progress: {
    limit: '500.00',
    spent: '120.00',
    remaining: '380.00',
    percent: 24,
    status: 'on_track',
    period_start: '2026-01-01',
    period_end: '2026-01-31',
  },
};

describe('BudgetsService', () => {
  let service: BudgetsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(BudgetsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/budgets lists budgets with progress and caches them', async () => {
    const promise = firstValueFrom(service.listBudgets());

    const req = httpMock.expectOne('/api/budgets');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush([BUDGET_RESPONSE]);

    const budgets = await promise;
    expect(budgets).toEqual([BUDGET_RESPONSE]);
    expect(service.budgets()).toEqual([BUDGET_RESPONSE]);
  });

  it('POST /api/budgets creates a budget with the exact body shape (task focus)', async () => {
    const promise = firstValueFrom(
      service.createBudget({
        category_id: 'cat-1',
        amount: '500.00',
        currency: 'USD',
      }),
    );

    const req = httpMock.expectOne('/api/budgets');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      category_id: 'cat-1',
      amount: '500.00',
      currency: 'USD',
    });
    req.flush(BUDGET_RESPONSE);

    const budget = await promise;
    expect(budget.id).toBe('budget-1');
  });

  it('GET /api/budgets/{id} fetches a single budget', async () => {
    const promise = firstValueFrom(service.getBudget('budget-1'));

    const req = httpMock.expectOne('/api/budgets/budget-1');
    expect(req.request.method).toBe('GET');
    req.flush(BUDGET_RESPONSE);

    const budget = await promise;
    expect(budget.id).toBe('budget-1');
  });

  it('PATCH /api/budgets/{id} updates only the fields present', async () => {
    const promise = firstValueFrom(service.updateBudget('budget-1', { amount: '600.00' }));

    const req = httpMock.expectOne('/api/budgets/budget-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ amount: '600.00' });
    req.flush({ ...BUDGET_RESPONSE, amount: '600.00' });

    const budget = await promise;
    expect(budget.amount).toBe('600.00');
  });

  it('DELETE /api/budgets/{id} deletes a budget', async () => {
    const promise = firstValueFrom(service.deleteBudget('budget-1'));

    const req = httpMock.expectOne('/api/budgets/budget-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });
});
