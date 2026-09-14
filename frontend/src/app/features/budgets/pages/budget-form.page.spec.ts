/**
 * `BudgetFormPage` (Phase 5 PR2, task 2.4) — covers the design Testing
 * Strategy's "form currency lock" (D73) plus create/edit submission and
 * verbatim 422 handling, mirroring `recurring-form.page.spec.ts`'s pattern.
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

import { BudgetFormPage } from './budget-form.page';

const ACCOUNT = {
  id: 'acc-1',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Checking',
  currency: 'EUR',
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

const BUDGET = {
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
    spent: '0.00',
    remaining: '500.00',
    percent: 0,
    status: 'on_track',
    period_start: '2026-01-01',
    period_end: '2026-01-31',
  },
};

const TRANSLATIONS = {
  budgets: {
    createTitle: 'Add budget',
    editTitle: 'Edit budget',
    loading: 'Loading…',
    loadError: 'Could not load.',
    category: 'Category',
    selectCategory: 'Select a category',
    account: 'Account',
    allAccounts: 'All accounts',
    name: 'Name',
    amount: 'Amount',
    currency: 'Currency',
    create: 'Create',
    save: 'Save',
    saveError: 'Could not save.',
  },
};

function activatedRouteWithId(id: string | null) {
  return { snapshot: { paramMap: convertToParamMap(id ? { id } : {}) } };
}

async function createFixture(id: string | null): Promise<ComponentFixture<BudgetFormPage>> {
  await TestBed.configureTestingModule({
    imports: [
      BudgetFormPage,
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

  return TestBed.createComponent(BudgetFormPage);
}

function flushLookups(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
  httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
}

describe('BudgetFormPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('create mode: submitting calls POST /api/budgets with the exact body shape (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['categoryId'].set('cat-1');
    component['amount'].set('500.00');
    component['currency'].set('USD');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/budgets');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      category_id: 'cat-1',
      account_id: null,
      name: null,
      amount: '500.00',
      currency: 'USD',
    });
    req.flush(BUDGET);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/budgets');
  });

  it('selecting an account pre-fills and locks the currency field (design D73, task focus)', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    expect(component['currencyLocked']()).toBe(false);

    component['setAccount']('acc-1');
    fixture.detectChanges();

    expect(component['currency']()).toBe('EUR');
    expect(component['currencyLocked']()).toBe(true);

    const currencyInput = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="budget-currency-input"] input',
    ) as HTMLInputElement | null;
    if (currencyInput) expect(currencyInput.disabled).toBe(true);
  });

  it('choosing "no account" again unlocks the currency field', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['setAccount']('acc-1');
    fixture.detectChanges();
    expect(component['currencyLocked']()).toBe(true);

    component['setAccount']('__none__');
    fixture.detectChanges();
    expect(component['currencyLocked']()).toBe(false);
  });

  it('edit mode: loads the existing budget and PATCHes only submitted fields', async () => {
    const fixture = await createFixture('budget-1');
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    httpMock.expectOne((r) => r.url === '/api/budgets/budget-1').flush(BUDGET);
    await fixture.whenStable();
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/budgets/budget-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({
      category_id: 'cat-1',
      account_id: null,
      name: null,
      amount: '500.00',
      currency: 'USD',
    });
    req.flush(BUDGET);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/budgets');
  });

  it('renders the verbatim server 422 detail (currency-mismatch validation, D73) via ui-alert [message]', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['categoryId'].set('cat-1');
    component['amount'].set('500.00');
    component['currency'].set('USD');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/budgets');
    req.flush(
      { detail: 'budget currency must match account currency' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="budget-server-error"]')?.textContent).toContain(
      'budget currency must match account currency',
    );
  });
});
