/**
 * `TransactionFormPage` — Phase 2 PR6 (task 7.3, BASIC case) + PR6b
 * (tasks 8.1/8.2/8.3: split-allocation editor + receipt-upload
 * pipeline). Real `HttpClient` against `HttpTestingController`,
 * `ActivatedRoute` mocked with `convertToParamMap` exactly like
 * `join.page.spec.ts` establishes for a route-param-driven page.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TransactionFormPage } from './transaction-form.page';

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
  name: 'Groceries',
  icon: null,
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

const UPLOAD_URL_RESPONSE = {
  url: 'https://walleza-receipts-staging.s3.amazonaws.com/',
  fields: { key: 'workspaces/ws-1/transactions/txn-1/receipt', 'Content-Type': 'image/jpeg' },
  expires_at: '2026-01-01T00:05:00Z',
  max_bytes: 5242880,
  content_type: 'image/jpeg',
};

const CONFIRM_RESPONSE = {
  photo_content_type: 'image/jpeg',
  photo_uploaded_at: '2026-01-01T00:01:00Z',
};

const TRANSLATIONS = {
  transactions: {
    createTitle: 'Add transaction',
    editTitle: 'Edit transaction',
    loading: 'Loading…',
    loadError: 'Could not load that transaction.',
    account: 'Account',
    selectAccount: 'Select an account',
    type: 'Type',
    expense: 'Expense',
    income: 'Income',
    amount: 'Amount',
    date: 'Date',
    notes: 'Notes',
    isRefund: 'Refund',
    checked: 'Checked',
    create: 'Create',
    save: 'Save',
    saveError: 'Could not save that transaction.',
    validationError: 'That transaction could not be validated.',
    splits: {
      title: 'Split across categories',
      category: 'Category',
      selectCategory: 'Select a category',
      amount: 'Amount',
      add: 'Add split',
      remove: 'Remove',
      allocatedTotal: 'Allocated',
      expectedTotal: 'Expected',
    },
    photo: {
      label: 'Receipt photo',
      uploading: 'Uploading…',
      uploadError: 'Could not upload that photo. Please try again.',
    },
  },
};

function activatedRouteWithId(id: string | null) {
  return {
    snapshot: { paramMap: convertToParamMap(id ? { id } : {}) },
  };
}

async function createFixture(id: string | null): Promise<ComponentFixture<TransactionFormPage>> {
  await TestBed.configureTestingModule({
    imports: [
      TransactionFormPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: ActivatedRoute, useValue: activatedRouteWithId(id) },
    ],
  }).compileComponents();

  return TestBed.createComponent(TransactionFormPage);
}

/** Flushes the two read-only lookups every mode of this page fires from
 * its constructor (`AccountsService.listAccounts`,
 * `CategoriesService.listCategories`) — neither is this test's own
 * focus, so they are always satisfied identically. */
function flushLookups(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
  httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
}

describe('TransactionFormPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('create mode: submitting the form calls POST /api/transactions with the exact BASIC-case body shape, money as a string (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['accountId'].set('acc-1');
    component['type'].set('expense');
    component['amount'].set('42.50');
    component['occurredOn'].set('2026-01-15');
    component['notes'].set('Groceries');
    component['isRefund'].set(false);
    component['checked'].set(false);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transactions');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '42.50',
      occurred_on: '2026-01-15',
      notes: 'Groceries',
      is_refund: false,
      checked: false,
    });
    expect(typeof req.request.body.amount).toBe('string');
    expect(req.request.body.splits).toBeUndefined();
    req.flush(TRANSACTION);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/transactions');
  });

  it('edit mode: loads the existing transaction via GET, then submitting calls PATCH /api/transactions/{id} (task focus)', async () => {
    const fixture = await createFixture('txn-1');
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);

    const getReq = httpMock.expectOne('/api/transactions/txn-1');
    expect(getReq.request.method).toBe('GET');
    getReq.flush(TRANSACTION);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    expect(component['accountId']()).toBe('acc-1');
    expect(component['amount']()).toBe('42.50');

    component['amount'].set('50.00');
    component['checked'].set(true);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const patchReq = httpMock.expectOne('/api/transactions/txn-1');
    expect(patchReq.request.method).toBe('PATCH');
    expect(patchReq.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '50.00',
      occurred_on: '2026-01-15',
      notes: 'Groceries',
      is_refund: false,
      checked: true,
    });
    expect(patchReq.request.body.splits).toBeUndefined();
    patchReq.flush({ ...TRANSACTION, amount: '50.00', checked: true });
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/transactions');
  });

  it('shows a validation error message on a 422 response without navigating away', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['accountId'].set('acc-1');
    component['amount'].set('42.50');
    component['occurredOn'].set('2026-01-15');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transactions');
    req.flush({ detail: 'invalid' }, { status: 422, statusText: 'Unprocessable Entity' });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'That transaction could not be validated.',
    );
  });

  it('includes non-empty split rows inline in the POST body (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['accountId'].set('acc-1');
    component['amount'].set('100.00');
    component['occurredOn'].set('2026-01-15');
    component['splitRows'].set([
      { category_id: 'cat-1', amount: '60.00' },
      { category_id: 'cat-2', amount: '40.00' },
    ]);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transactions');
    expect(req.request.body.splits).toEqual([
      { category_id: 'cat-1', amount: '60.00' },
      { category_id: 'cat-2', amount: '40.00' },
    ]);
    req.flush({ ...TRANSACTION, splits: [] });
    await fixture.whenStable();
  });

  it('renders the server-authoritative expected/allocated totals on a split-mismatch 422, without navigating away (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['accountId'].set('acc-1');
    component['amount'].set('100.00');
    component['occurredOn'].set('2026-01-15');
    component['splitRows'].set([{ category_id: 'cat-1', amount: '90.00' }]);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transactions');
    // The EXACT `detail` shape `TransactionSplitValidationError` actually
    // raises (`backend/app/transactions/service.py`) — a prose string,
    // not a structured `{expected_total, allocated_total}` body.
    req.flush(
      {
        detail:
          'split amounts must sum exactly to the transaction amount (got 90.00, expected 100.00)',
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    const el = fixture.nativeElement as HTMLElement;
    // The generic banner must NOT fire — this is routed to the split
    // editor's own mismatch rendering instead.
    expect(el.textContent).not.toContain('That transaction could not be validated.');
    expect(el.querySelector('[data-testid="split-allocated-total"]')?.textContent).toContain(
      '90.00',
    );
    expect(el.querySelector('[data-testid="split-expected-total"]')?.textContent).toContain(
      '100.00',
    );
  });

  it('edit mode seeds the split editor from the existing transaction splits', async () => {
    const fixture = await createFixture('txn-1');
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);

    const getReq = httpMock.expectOne('/api/transactions/txn-1');
    getReq.flush({
      ...TRANSACTION,
      splits: [{ id: 'split-1', category_id: 'cat-1', amount: '42.50' }],
    });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.componentInstance['splitRows']()).toEqual([
      { category_id: 'cat-1', amount: '42.50' },
    ]);
  });

  it('runs the receipt-upload pipeline after a successful create, navigating only once the confirm step resolves (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['accountId'].set('acc-1');
    component['amount'].set('42.50');
    component['occurredOn'].set('2026-01-15');
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const fileInput = el.querySelector('[data-testid="receipt-file-input"]') as HTMLInputElement;
    const file = new File(['bytes'], 'receipt.jpg', { type: 'image/jpeg' });
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fileInput.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    const form = el.querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const createReq = httpMock.expectOne('/api/transactions');
    createReq.flush(TRANSACTION);
    await fixture.whenStable();

    // Navigation must NOT have happened yet — the photo pipeline is still
    // pending after transaction creation.
    expect(navigateSpy).not.toHaveBeenCalled();

    const uploadUrlReq = httpMock.expectOne('/api/transactions/txn-1/photo/upload-url');
    expect(uploadUrlReq.request.body).toEqual({ content_type: 'image/jpeg' });
    uploadUrlReq.flush(UPLOAD_URL_RESPONSE);

    const s3Req = httpMock.expectOne(UPLOAD_URL_RESPONSE.url);
    expect(s3Req.request.withCredentials).toBe(false);
    httpMock.expectNone('/api/transactions/txn-1/photo');
    s3Req.flush(null);

    const confirmReq = httpMock.expectOne('/api/transactions/txn-1/photo');
    expect(confirmReq.request.method).toBe('PUT');
    confirmReq.flush(CONFIRM_RESPONSE);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/transactions');
  });
});
