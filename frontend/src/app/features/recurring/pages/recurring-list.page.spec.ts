/**
 * `RecurringListPage` (Phase 4 PR5, task 5.2) — ALSO the ENTIRE
 * Subscriptions implementation (design D56): when instantiated with
 * `route.snapshot.data['subscriptionsOnly'] === true` (exactly what
 * `recurring.routes.ts`'s `'subscriptions'` path sets), the SAME
 * component presets `is_subscription: true` on its own `GET /api/recurring`
 * call — proving there is no second entity/service/route for it.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it } from 'vitest';

import { RecurringListPage } from './recurring-list.page';

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
    title: 'Recurring transactions',
    subscriptionsTitle: 'Subscriptions',
    loading: 'Loading…',
    loadError: 'Could not load.',
    create: 'Add',
    edit: 'Edit',
    delete: 'Delete',
    deleteError: 'Could not delete.',
    isSubscription: 'Subscription',
  },
};

async function createFixture(subscriptionsOnly: boolean): Promise<ComponentFixture<RecurringListPage>> {
  await TestBed.configureTestingModule({
    imports: [
      RecurringListPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { data: { subscriptionsOnly } } },
      },
    ],
  }).compileComponents();

  return TestBed.createComponent(RecurringListPage);
}

describe('RecurringListPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('plain route (subscriptionsOnly=false): GET /api/recurring is called with NO is_subscription param', async () => {
    const fixture = await createFixture(false);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);

    const req = httpMock.expectOne((r) => r.url === '/api/recurring');
    expect(req.request.params.has('is_subscription')).toBe(false);
    req.flush([RECURRING]);
    await fixture.whenStable();
  });

  it('Subscriptions route (subscriptionsOnly=true): GET /api/recurring is called with is_subscription=true (task focus)', async () => {
    const fixture = await createFixture(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);

    const req = httpMock.expectOne((r) => r.url === '/api/recurring');
    expect(req.request.params.get('is_subscription')).toBe('true');
    req.flush([RECURRING]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Subscriptions');
  });

  it('clicking delete calls DELETE /api/recurring/{id} and reloads', async () => {
    const fixture = await createFixture(false);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    httpMock.expectOne((r) => r.url === '/api/recurring').flush([RECURRING]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    deleteButton?.click();

    const req = httpMock.expectOne('/api/recurring/recurring-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    httpMock.expectOne((r) => r.url === '/api/recurring').flush([]);
    await fixture.whenStable();
  });
});
