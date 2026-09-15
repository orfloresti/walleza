/**
 * `ReceiptConfirmPage` — Phase 9, Unit 9 (design D134): the hand-off fast
 * path, the independent-fetch fallback for a `null` `consume()` result
 * (page refresh), the `extraction_failed` graceful manual fallback, a
 * successful confirm + navigation, 409/422 error handling, and the
 * category-always-required/never-pre-filled invariant.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { OcrCaptureHandoffService } from '../data/ocr-capture-handoff.service';
import { ReceiptConfirmPage } from './receipt-confirm.page';

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

const EXTRACTION: {
  status: 'succeeded' | 'failed';
  failure_reason: null;
  amount: string;
  occurred_on: string;
  vendor_name: string;
  currency: string;
  field_confidence: Record<string, number>;
} = {
  status: 'succeeded',
  failure_reason: null,
  amount: '12.34',
  occurred_on: '2026-01-15',
  vendor_name: 'Coffee Shop',
  currency: 'USD',
  field_confidence: { amount: 99.1, occurred_on: 40.0 },
};

const TRANSLATIONS = {
  transactions: {
    account: 'Account',
    selectAccount: 'Select an account',
    type: 'Type',
    amount: 'Amount',
    date: 'Date',
    notes: 'Notes',
    isRefund: 'Refund',
    checked: 'Checked',
    validationError: 'That transaction could not be validated.',
    splits: { category: 'Category', selectCategory: 'Select a category' },
    scan: {
      confirmTitle: 'Confirm receipt details',
      confirmLoading: 'Loading receipt details…',
      confirmSubmit: 'Confirm',
      confirmError: 'Could not confirm that transaction.',
      confirmConflictError: 'This receipt was already confirmed or is no longer available.',
      extractionFailedBody: "We couldn't read this receipt automatically.",
      stillProcessing: "We're still reading your receipt.",
      proceedManually: 'Continue manually',
      lowConfidence: 'check this',
    },
  },
};

function flushAccountsAndCategories(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url.startsWith('/api/accounts')).flush([ACCOUNT]);
  httpMock.expectOne((r) => r.url.startsWith('/api/categories')).flush([CATEGORY]);
}

async function configureModule(id: string): Promise<void> {
  await TestBed.configureTestingModule({
    imports: [
      ReceiptConfirmPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: { get: () => id } } },
      },
    ],
  }).compileComponents();
}

async function createFixture(
  id = 'txn-draft-1',
  beforeCreate?: () => void,
): Promise<ComponentFixture<ReceiptConfirmPage>> {
  await configureModule(id);
  // `beforeCreate` runs AFTER the module is configured but BEFORE the
  // component is created — the handoff-priming test needs
  // `OcrCaptureHandoffService.set()` to land before the page's
  // constructor calls `consume()`.
  beforeCreate?.();
  return TestBed.createComponent(ReceiptConfirmPage);
}

function selectCategory(fixture: ComponentFixture<ReceiptConfirmPage>, categoryId: string): void {
  const select = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="confirm-category-select"]',
  ) as HTMLSelectElement;
  select.value = categoryId;
  select.dispatchEvent(new Event('change'));
  fixture.detectChanges();
}

function submit(fixture: ComponentFixture<ReceiptConfirmPage>): void {
  const form = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="confirm-form"]',
  ) as HTMLFormElement;
  form.dispatchEvent(new Event('submit'));
  fixture.detectChanges();
}

describe('ReceiptConfirmPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('renders pre-filled data with low-confidence badges from the hand-off fast path', async () => {
    const fixture = await createFixture('txn-draft-1', () => {
      // Prime the handoff service BEFORE the component under test is
      // constructed, so its constructor sees the held value on
      // `consume()`.
      TestBed.inject(OcrCaptureHandoffService).set({
        transactionId: 'txn-draft-1',
        accountId: 'acc-1',
        ocrStatus: 'extracted',
        extraction: EXTRACTION,
        timedOut: false,
      });
    });
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect((el.querySelector('[data-testid="confirm-amount-input"]') as HTMLInputElement).value).toBe(
      '12.34',
    );
    expect((el.querySelector('[data-testid="confirm-date-input"]') as HTMLInputElement).value).toBe(
      '2026-01-15',
    );
    expect((el.querySelector('[data-testid="confirm-notes-input"]') as HTMLInputElement).value).toBe(
      'Coffee Shop',
    );

    // amount confidence 99.1 -> no badge; occurred_on confidence 40.0 -> badge.
    expect(el.querySelector('[data-testid="confirm-amount-badge"]')).toBeNull();
    expect(el.querySelector('[data-testid="confirm-date-badge"]')).not.toBeNull();

    // Category is NEVER pre-filled, always required.
    expect(
      (el.querySelector('[data-testid="confirm-category-select"]') as HTMLSelectElement).value,
    ).toBe('');
    expect(
      (el.querySelector('[data-testid="confirm-submit-button"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('falls back to an independent getOcrStatus fetch when consume() returns null (page refresh)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    const ocrReq = httpMock.expectOne('/api/transactions/txn-draft-1/ocr');
    ocrReq.flush({ ocr_status: 'extracted', account_id: 'acc-1', extraction: EXTRACTION });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect((el.querySelector('[data-testid="confirm-amount-input"]') as HTMLInputElement).value).toBe(
      '12.34',
    );
    // The regression this test guards: on the null-consume() fallback,
    // `account_id` MUST come from the poll response, never stay the
    // initial empty-string signal — otherwise the user's account
    // selection is silently lost on a page refresh mid-review.
    expect(
      (el.querySelector('[data-testid="confirm-account-select"]') as HTMLSelectElement).value,
    ).toBe('acc-1');
  });

  it('shows the extraction_failed alert and an all-empty manual form (graceful fallback, not a dead end)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extraction_failed', account_id: 'acc-1', extraction: null });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="confirm-extraction-failed-alert"]')).not.toBeNull();
    expect((el.querySelector('[data-testid="confirm-amount-input"]') as HTMLInputElement).value).toBe(
      '',
    );
    expect(
      (el.querySelector('[data-testid="confirm-category-select"]') as HTMLSelectElement).value,
    ).toBe('');
  });

  it('a non-terminal pending_ocr fallback offers manual entry rather than a confirm attempt', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'pending_ocr', account_id: 'acc-1', extraction: null });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="confirm-processing"]'),
    ).not.toBeNull();
  });

  it('submits confirm-from-photo and navigates to the transactions list on success', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extracted', account_id: 'acc-1', extraction: EXTRACTION });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    selectCategory(fixture, 'cat-1');
    submit(fixture);

    const req = httpMock.expectOne('/api/transactions/txn-draft-1/confirm-from-photo');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '12.34',
      occurred_on: '2026-01-15',
      notes: 'Coffee Shop',
      is_refund: false,
      checked: false,
      splits: [{ category_id: 'cat-1', amount: '12.34' }],
    });
    req.flush({ id: 'txn-draft-1' });

    expect(navigateSpy).toHaveBeenCalledWith('/transactions');
  });

  it('surfaces a 409 as a conflict error, not the generic confirm error', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extracted', account_id: 'acc-1', extraction: EXTRACTION });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    selectCategory(fixture, 'cat-1');
    submit(fixture);

    httpMock
      .expectOne('/api/transactions/txn-draft-1/confirm-from-photo')
      .flush({ detail: 'already confirmed' }, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="confirm-error"]')
        ?.textContent,
    ).toContain('already confirmed or is no longer available');
  });

  it('surfaces a 422 (e.g. missing category) as a field-level validation error', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extracted', account_id: 'acc-1', extraction: EXTRACTION });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    selectCategory(fixture, 'cat-1');
    submit(fixture);

    httpMock
      .expectOne('/api/transactions/txn-draft-1/confirm-from-photo')
      .flush({ detail: 'validation error' }, { status: 422, statusText: 'Unprocessable Entity' });
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="confirm-error"]')
        ?.textContent,
    ).toContain('could not be validated');
  });

  it('never allows submit without a category selected, even with a fully pre-filled form', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extracted', account_id: 'acc-1', extraction: EXTRACTION });
    flushAccountsAndCategories(httpMock);
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector(
        '[data-testid="confirm-submit-button"]',
      ) as HTMLButtonElement,
    ).toHaveProperty('disabled', true);

    const accountSelect = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="confirm-account-select"]',
    ) as HTMLSelectElement;
    accountSelect.value = 'acc-1';
    accountSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    selectCategory(fixture, 'cat-1');

    expect(
      (fixture.nativeElement as HTMLElement).querySelector(
        '[data-testid="confirm-submit-button"]',
      ) as HTMLButtonElement,
    ).toHaveProperty('disabled', false);
  });
});
