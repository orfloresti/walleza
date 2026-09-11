/**
 * `RecurringFormPage` (Phase 4 PR5, task 5.2): create/edit form, reusing
 * the shared split-allocation editor, plus design D48's backfill warning
 * for a past `starts_on`. Real `HttpClient` against
 * `HttpTestingController`, `ActivatedRoute` mocked exactly like
 * `template-form.page.spec.ts`.
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

import { RecurringFormPage } from './recurring-form.page';

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
  name: 'Subscriptions',
  icon: null,
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const RECURRING = {
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

const TRANSLATIONS = {
  recurring: {
    createTitle: 'Add recurring transaction',
    editTitle: 'Edit recurring transaction',
    loading: 'Loading…',
    loadError: 'Could not load.',
    account: 'Account',
    selectAccount: 'Select an account',
    type: 'Type',
    expense: 'Expense',
    income: 'Income',
    amount: 'Amount',
    notes: 'Notes',
    isRefund: 'Refund',
    isSubscription: 'Subscription',
    repeatEvery: 'Repeat every',
    period: 'Period',
    periodDay: 'Day(s)',
    periodWeek: 'Week(s)',
    periodMonth: 'Month(s)',
    periodYear: 'Year(s)',
    startsOn: 'Starts on',
    endsOn: 'Ends on',
    reminderDaysBefore: 'Remind me',
    reminderLocale: 'Reminder language',
    create: 'Create',
    save: 'Save',
    saveError: 'Could not save.',
    backfillWarning: 'This start date is in the past — every missed occurrence will be generated.',
  },
  transactions: {
    splits: {
      title: 'Splits',
      category: 'Category',
      selectCategory: 'Select a category',
      amount: 'Amount',
      add: 'Add split',
      remove: 'Remove',
      allocatedTotal: 'Allocated',
      expectedTotal: 'Expected',
    },
  },
};

function activatedRouteWithId(id: string | null) {
  return { snapshot: { paramMap: convertToParamMap(id ? { id } : {}) } };
}

async function createFixture(id: string | null): Promise<ComponentFixture<RecurringFormPage>> {
  await TestBed.configureTestingModule({
    imports: [
      RecurringFormPage,
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

  return TestBed.createComponent(RecurringFormPage);
}

function flushLookups(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
  httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
}

describe('RecurringFormPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('create mode: submitting calls POST /api/recurring with the exact body shape, never sending next_date (task focus)', async () => {
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
    component['amount'].set('9.99');
    component['repeatEvery'].set(1);
    component['period'].set('month');
    component['startsOn'].set('2099-01-01');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/recurring');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '9.99',
      notes: null,
      is_refund: false,
      is_subscription: false,
      repeat_every: 1,
      period: 'month',
      starts_on: '2099-01-01',
      ends_on: null,
      reminder_days_before: null,
      reminder_locale: 'en',
    });
    expect('next_date' in req.request.body).toBe(false);
    req.flush(RECURRING);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/recurring');
  });

  it('does NOT render the backfill warning for a starts_on in the future', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    fixture.componentInstance['startsOn'].set('2099-01-01');
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="recurring-backfill-warning"]'),
    ).toBeNull();
  });

  it('renders the backfill warning (design D48) when starts_on is in the past, and only in create mode (task focus)', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    fixture.componentInstance['startsOn'].set('2000-01-01');
    fixture.detectChanges();

    const warning = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="recurring-backfill-warning"]',
    );
    expect(warning?.textContent).toContain('every missed occurrence will be generated');
  });

  it('edit mode: loads the existing recurrence via GET, never shows a starts_on input, and PATCHes on submit', async () => {
    const fixture = await createFixture('recurring-1');
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);

    const getReq = httpMock.expectOne('/api/recurring/recurring-1');
    getReq.flush(RECURRING);
    await fixture.whenStable();
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="recurring-starts-on-input"]'),
    ).toBeNull();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="recurring-backfill-warning"]'),
    ).toBeNull();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const patchReq = httpMock.expectOne('/api/recurring/recurring-1');
    expect(patchReq.request.method).toBe('PATCH');
    expect('starts_on' in patchReq.request.body).toBe(false);
    patchReq.flush(RECURRING);
    await fixture.whenStable();
  });

  it('renders the server 422 detail verbatim on save failure, without navigating away (task focus)', async () => {
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
    component['amount'].set('9.99');
    component['repeatEvery'].set(1);
    component['period'].set('month');
    component['startsOn'].set('2099-01-01');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/recurring');
    req.flush(
      { detail: 'ends_on must not be before starts_on' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="recurring-server-error"]')?.textContent).toContain(
      'ends_on must not be before starts_on',
    );
  });
});
