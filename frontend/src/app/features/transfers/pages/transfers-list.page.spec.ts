/**
 * `TransfersListPage` (Phase 3 PR2, task 2.3): renders `GET /api/transfers`
 * and re-requests it with the correct query params when a filter control
 * changes. Real `HttpClient` against `HttpTestingController`, no live
 * backend — same pattern as `transactions-list.page.spec.ts`. The page
 * also loads accounts (for the filter dropdown and from/to name
 * rendering), so every test flushes that request too.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { TransfersListPage } from './transfers-list.page';

const ACCOUNT_A = {
  id: 'acc-1',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Checking',
  currency: 'USD',
  exchange_rate: '1',
  initial_funds: '100.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const ACCOUNT_B = {
  id: 'acc-2',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Savings',
  currency: 'USD',
  exchange_rate: '1',
  initial_funds: '0.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TRANSFER = {
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

const TRANSLATIONS = {
  transfers: {
    title: 'Transfers',
    loading: 'Loading…',
    loadError: 'Could not load transfers.',
    create: 'Add transfer',
    delete: 'Delete',
    deleteError: 'Could not delete that transfer.',
    filterAccount: 'Account',
    filterDateFrom: 'From',
    filterDateTo: 'To',
    filterAll: 'All',
    balanceNotice: 'Transfers are recorded here but do not yet change any account balance.',
  },
};

describe('TransfersListPage', () => {
  let fixture: ComponentFixture<TransfersListPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        TransfersListPage,
        TranslocoTestingModule.forRoot({
          langs: { en: TRANSLATIONS },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TransfersListPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushBootstrapRequests(): void {
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT_A, ACCOUNT_B]);
  }

  it('renders the list from GET /api/transfers with both account names, both amounts, and the P6-boundary notice', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();

    const req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.keys().length).toBe(0);
    req.flush([TRANSFER]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Checking');
    expect(text).toContain('Savings');
    expect(text).toContain('100.00');
    expect(text).toContain('50.00');
    expect(text).toContain('do not yet change any account balance');
  });

  it('changing the account filter re-requests the list with account_id set (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transfers').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const select = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="filter-account"]',
    ) as HTMLSelectElement;
    select.value = 'acc-1';
    select.dispatchEvent(new Event('change'));

    const req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    req.flush([]);
    await fixture.whenStable();
  });

  it('changing the date range filters re-requests the list with both params (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transfers').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['setDateFromFilter']('2026-01-01');
    let req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    req.flush([]);
    await fixture.whenStable();

    component['setDateToFilter']('2026-01-31');
    req = httpMock.expectOne((r) => r.url === '/api/transfers');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    req.flush([]);
    await fixture.whenStable();
  });

  it('clicking delete calls DELETE /api/transfers/{id}', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transfers').flush([TRANSFER]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    expect(deleteButton).toBeTruthy();
    deleteButton?.click();

    const req = httpMock.expectOne('/api/transfers/transfer-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    // deleteTransfer() reloads the list afterwards.
    httpMock.expectOne((r) => r.url === '/api/transfers').flush([]);
    await fixture.whenStable();
  });
});
