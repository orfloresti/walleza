/**
 * `ReportsService` HTTP contract tests, same `HttpTestingController`
 * pattern `budgets.service.spec.ts` established — proves each call hits
 * the exact path/method/query-params `app/reports/{router,schemas}.py`
 * defines.
 */

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ReportsService } from './reports.service';

const BREAKDOWN_RESPONSE = {
  currency: 'USD',
  date_from: '2026-01-01',
  date_to: '2026-01-31',
  slices: [
    { category_id: 'cat-1', name: 'Groceries', parent_id: null, own: '100.00', total: '100.00' },
  ],
};

const TREND_RESPONSE = {
  currency: 'USD',
  bucket: 'month',
  date_from: '2026-01-01',
  date_to: '2026-01-31',
  points: [
    { bucket_start: '2026-01-01', bucket_end: '2026-01-31', partial: false, total: '100.00' },
  ],
};

describe('ReportsService', () => {
  let service: ReportsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ReportsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/reports/category-breakdown sends resolved-date query params', async () => {
    const promise = firstValueFrom(
      service.getCategoryBreakdown({
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        currency: 'USD',
        type: 'expense',
      }),
    );

    const req = httpMock.expectOne(
      (r) => r.url === '/api/reports/category-breakdown',
    );
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    expect(req.request.params.get('currency')).toBe('USD');
    expect(req.request.params.get('type')).toBe('expense');
    req.flush(BREAKDOWN_RESPONSE);

    const result = await promise;
    expect(result).toEqual(BREAKDOWN_RESPONSE);
  });

  it('GET /api/reports/trend sends the bucket param independently of the date range', async () => {
    const promise = firstValueFrom(
      service.getTrend({
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        currency: 'USD',
        bucket: 'month',
      }),
    );

    const req = httpMock.expectOne((r) => r.url === '/api/reports/trend');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('bucket')).toBe('month');
    req.flush(TREND_RESPONSE);

    const result = await promise;
    expect(result).toEqual(TREND_RESPONSE);
  });

  it('GET /api/reports/default-currency fetches the workspace default', async () => {
    const promise = firstValueFrom(service.getDefaultCurrency());

    const req = httpMock.expectOne('/api/reports/default-currency');
    expect(req.request.method).toBe('GET');
    req.flush({ currency: 'USD' });

    const result = await promise;
    expect(result).toEqual({ currency: 'USD' });
  });

  it('GET /api/reports/default-currency can resolve currency: null for an empty workspace', async () => {
    const promise = firstValueFrom(service.getDefaultCurrency());

    const req = httpMock.expectOne('/api/reports/default-currency');
    req.flush({ currency: null });

    const result = await promise;
    expect(result.currency).toBeNull();
  });
});
