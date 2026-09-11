/**
 * `TemplateFormPage` (Phase 4 PR5, task 5.1): create/edit form, reusing
 * the shared split-allocation editor. Real `HttpClient` against
 * `HttpTestingController`, `ActivatedRoute` mocked with
 * `convertToParamMap` exactly like `transaction-form.page.spec.ts`
 * establishes for a route-param-driven page.
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

import { TemplateFormPage } from './template-form.page';

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
  name: 'Rent',
  icon: null,
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TEMPLATE = {
  id: 'template-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  name: 'Rent',
  position: 0,
  type: 'expense',
  amount: '1200.00',
  notes: null,
  created_by_user_id: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  splits: [],
};

const TRANSLATIONS = {
  templates: {
    createTitle: 'Add template',
    editTitle: 'Edit template',
    loading: 'Loading…',
    loadError: 'Could not load that template.',
    name: 'Name',
    account: 'Account',
    selectAccount: 'Select an account',
    type: 'Type',
    expense: 'Expense',
    income: 'Income',
    amount: 'Amount',
    notes: 'Notes',
    position: 'Position',
    create: 'Create',
    save: 'Save',
    saveError: 'Could not save that template.',
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

async function createFixture(id: string | null): Promise<ComponentFixture<TemplateFormPage>> {
  await TestBed.configureTestingModule({
    imports: [
      TemplateFormPage,
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

  return TestBed.createComponent(TemplateFormPage);
}

function flushLookups(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
  httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
}

describe('TemplateFormPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('create mode: submitting the form calls POST /api/templates with the exact body shape (task focus)', async () => {
    const fixture = await createFixture(null);
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['name'].set('Rent');
    component['accountId'].set('acc-1');
    component['type'].set('expense');
    component['amount'].set('1200.00');
    component['position'].set(0);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/templates');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Rent',
      account_id: 'acc-1',
      type: 'expense',
      amount: '1200.00',
      notes: null,
      position: 0,
    });
    req.flush(TEMPLATE);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/templates');
  });

  it('edit mode: loads the existing template via GET, then submitting calls PATCH /api/templates/{id}', async () => {
    const fixture = await createFixture('template-1');
    const router = TestBed.inject(Router);
    vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);

    const getReq = httpMock.expectOne('/api/templates/template-1');
    getReq.flush(TEMPLATE);
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.componentInstance['name']()).toBe('Rent');

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const patchReq = httpMock.expectOne('/api/templates/template-1');
    expect(patchReq.request.method).toBe('PATCH');
    patchReq.flush(TEMPLATE);
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
    component['name'].set('Rent');
    component['accountId'].set('acc-1');
    component['amount'].set('1200.00');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/templates');
    req.flush(
      { detail: 'account not found' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="template-server-error"]')?.textContent).toContain(
      'account not found',
    );
  });

  it('renders a split-sum mismatch 422 through the split editor mismatch input, not the generic server-error banner', async () => {
    const fixture = await createFixture(null);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushLookups(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['name'].set('Rent');
    component['accountId'].set('acc-1');
    component['amount'].set('1200.00');
    component['splitRows'].set([{ category_id: 'cat-1', amount: '900.00' }]);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/templates');
    req.flush(
      {
        detail:
          'split amounts must sum exactly to the template amount (got 900.00, expected 1200.00)',
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="split-mismatch-error"]')?.textContent).toContain(
      'split amounts must sum exactly',
    );
    expect(el.querySelector('[data-testid="template-server-error"]')).toBeNull();
  });
});
