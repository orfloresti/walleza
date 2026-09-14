/**
 * `BudgetsListPage` (Phase 5 PR2, task 2.3) — covers the design Testing
 * Strategy's "list renders all three badge states" and the empty/error/
 * delete branches, mirroring `recurring-list.page.spec.ts`'s pattern.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it } from 'vitest';

import { BudgetsListPage } from './budgets-list.page';

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

function budgetFixture(id: string, status: 'on_track' | 'near_limit' | 'over_budget') {
  return {
    id,
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
      spent: '100.00',
      remaining: '400.00',
      percent: 20,
      status,
      period_start: '2026-01-01',
      period_end: '2026-01-31',
    },
  };
}

const TRANSLATIONS = {
  budgets: {
    title: 'Budgets',
    loading: 'Loading…',
    loadError: 'Could not load.',
    create: 'Add budget',
    edit: 'Edit',
    delete: 'Delete',
    deleteError: 'Could not delete.',
    allAccounts: 'All accounts',
    status: {
      on_track: 'On track',
      near_limit: 'Near limit',
      over_budget: 'Over budget',
    },
    empty: {
      title: 'No budgets yet',
      body: 'Budgets you create will show up here.',
    },
  },
};

async function createFixture(): Promise<ComponentFixture<BudgetsListPage>> {
  await TestBed.configureTestingModule({
    imports: [
      BudgetsListPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  }).compileComponents();

  return TestBed.createComponent(BudgetsListPage);
}

describe('BudgetsListPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('renders a badge for each of the three progress statuses (task focus)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
    httpMock
      .expectOne((r) => r.url === '/api/budgets')
      .flush([
        budgetFixture('budget-1', 'on_track'),
        budgetFixture('budget-2', 'near_limit'),
        budgetFixture('budget-3', 'over_budget'),
      ]);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const badges = el.querySelectorAll('[data-testid="budget-status-badge"]');
    expect(badges.length).toBe(3);
    expect(badges[0].textContent).toContain('On track');
    expect(badges[1].textContent).toContain('Near limit');
    expect(badges[2].textContent).toContain('Over budget');
  });

  it('shows "All accounts" for a category-only budget', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
    httpMock.expectOne((r) => r.url === '/api/budgets').flush([budgetFixture('budget-1', 'on_track')]);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="budget-account"]')?.textContent).toContain(
      'All accounts',
    );
  });

  it('renders the empty state when there are no budgets', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
    httpMock.expectOne((r) => r.url === '/api/budgets').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="budgets-empty"]')).toBeTruthy();
    expect(el.querySelector('[data-testid="budgets-list"]')).toBeFalsy();
  });

  it('shows the load error alert when the list request fails', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
    httpMock
      .expectOne((r) => r.url === '/api/budgets')
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Could not load.');
  });

  it('clicking delete calls DELETE /api/budgets/{id} and reloads', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/categories').flush([CATEGORY]);
    httpMock
      .expectOne((r) => r.url === '/api/budgets')
      .flush([budgetFixture('budget-1', 'on_track')]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    deleteButton?.click();

    const req = httpMock.expectOne('/api/budgets/budget-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    httpMock.expectOne((r) => r.url === '/api/budgets').flush([]);
    await fixture.whenStable();
  });
});
