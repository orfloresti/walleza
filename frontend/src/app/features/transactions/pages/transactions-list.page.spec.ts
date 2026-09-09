/**
 * `TransactionsListPage` — Phase 2 PR6 (task 7.2): renders the
 * workspace-wide `GET /api/transactions` feed and re-requests it with
 * the correct query params when a filter control changes. Real
 * `HttpClient` against `HttpTestingController`, no live backend — same
 * pattern as `accounts-list.page.spec.ts`. The page also loads accounts
 * and categories (for the filter dropdowns and account-name rendering),
 * so every test flushes those two requests too.
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

import { TransactionsListPage } from './transactions-list.page';

const ACCOUNT = {
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

const CATEGORY = {
  id: 'cat-1',
  workspace_id: 'ws-1',
  parent_id: null,
  name: 'Food',
  icon: '🍔',
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TRANSACTION = {
  id: 'txn-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  type: 'expense',
  amount: '42.50',
  occurred_on: '2026-01-15',
  notes: 'Groceries',
  is_refund: false,
  checked: false,
  photo_content_type: null,
  photo_uploaded_at: null,
  created_by_user_id: 'user-1',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z',
  splits: [],
};

const TRANSLATIONS = {
  transactions: {
    title: 'Transactions',
    create: 'Add transaction',
    edit: 'Edit',
    delete: 'Delete',
    deleteError: 'Could not delete that transaction.',
    loading: 'Loading…',
    loadError: 'Could not load transactions.',
    filterAccount: 'Account',
    filterCategory: 'Category',
    filterDateFrom: 'From',
    filterDateTo: 'To',
    filterType: 'Type',
    filterAll: 'All',
    expense: 'Expense',
    income: 'Income',
    refundBadge: 'Refund',
    checkedBadge: 'Checked',
  },
};

describe('TransactionsListPage', () => {
  let fixture: ComponentFixture<TransactionsListPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        TransactionsListPage,
        TranslocoTestingModule.forRoot({
          langs: { en: TRANSLATIONS },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TransactionsListPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushBootstrapRequests(): void {
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
  }

  it('renders the workspace-wide feed from GET /api/transactions with no filters by default', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();

    const req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.keys().length).toBe(0);
    req.flush([TRANSACTION]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('42.50');
    expect(text).toContain('Checking');
  });

  it('changing the account filter re-requests the feed with account_id set (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transactions').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const select = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="filter-account"]',
    ) as HTMLSelectElement;
    select.value = 'acc-1';
    select.dispatchEvent(new Event('change'));

    const req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    req.flush([]);
    await fixture.whenStable();
  });

  it('changing the date range and type filters re-requests the feed with all provided query params (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transactions').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['setDateFromFilter']('2026-01-01');
    let req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    req.flush([]);
    await fixture.whenStable();

    component['setDateToFilter']('2026-01-31');
    req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    req.flush([]);
    await fixture.whenStable();

    component['setTypeFilter']('expense');
    req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    expect(req.request.params.get('type')).toBe('expense');
    req.flush([]);
    await fixture.whenStable();
  });

  it('clicking delete calls DELETE /api/transactions/{id}', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/transactions').flush([TRANSACTION]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    expect(deleteButton).toBeTruthy();
    deleteButton?.click();

    const req = httpMock.expectOne('/api/transactions/txn-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    // deleteTransaction() reloads the feed afterwards.
    httpMock.expectOne((r) => r.url === '/api/transactions').flush([]);
    await fixture.whenStable();
  });
});
