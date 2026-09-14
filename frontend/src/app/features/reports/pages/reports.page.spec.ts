/**
 * `ReportsPage` (Phase 6 PR2a) — covers the design Testing Strategy's
 * "filter → query-param round trip" and "currency defaults from API when
 * absent" rows, plus the D92 empty-state guard sitting above chart
 * construction.
 */

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, ParamMap, Router } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { BehaviorSubject } from 'rxjs';
import { afterEach, describe, expect, it } from 'vitest';

import { ReportsPage } from './reports.page';

const TRANSLATIONS = {
  reports: {
    title: 'Reports',
    loading: 'Loading…',
    loadError: 'Could not load.',
    filterDateRange: 'Date range',
    filterCustomFrom: 'From',
    filterCustomTo: 'To',
    filterBucket: 'Group by',
    filterCurrency: 'Currency',
    filterType: 'Type',
    preset: {
      this_month: 'This month',
      last_3_months: 'Last 3 months',
      year_to_date: 'Year to date',
      custom: 'Custom range',
    },
    bucket: { day: 'Day', week: 'Week', month: 'Month', year: 'Year' },
    type: { expense: 'Expense', income: 'Income' },
    empty: { title: 'No activity', body: 'Nothing here.' },
  },
};

const BREAKDOWN_WITH_ACTIVITY = {
  currency: 'USD',
  date_from: '2026-09-01',
  date_to: '2026-09-30',
  slices: [{ category_id: 'cat-1', name: 'Groceries', parent_id: null, own: '10.00', total: '10.00' }],
};

const BREAKDOWN_EMPTY = {
  currency: 'USD',
  date_from: '2026-09-01',
  date_to: '2026-09-30',
  slices: [{ category_id: 'cat-1', name: 'Groceries', parent_id: null, own: '0', total: '0' }],
};

const TREND_EMPTY = {
  currency: 'USD',
  bucket: 'month',
  date_from: '2026-09-01',
  date_to: '2026-09-30',
  points: [{ bucket_start: '2026-09-01', bucket_end: '2026-09-30', partial: false, total: '0' }],
};

const TREND_WITH_ACTIVITY = {
  ...TREND_EMPTY,
  points: [{ ...TREND_EMPTY.points[0], total: '10.00' }],
};

class FakeActivatedRoute {
  private readonly subject: BehaviorSubject<ParamMap>;
  readonly queryParamMap;

  constructor(initial: Record<string, string>) {
    this.subject = new BehaviorSubject<ParamMap>(convertToParamMap(initial));
    this.queryParamMap = this.subject.asObservable();
  }

  setParams(params: Record<string, string>): void {
    this.subject.next(convertToParamMap(params));
  }

  get current(): Record<string, string> {
    const map = this.subject.value;
    const result: Record<string, string> = {};
    for (const key of map.keys) {
      result[key] = map.get(key) ?? '';
    }
    return result;
  }
}

class FakeRouter {
  constructor(private readonly route: FakeActivatedRoute) {}

  navigate(_commands: unknown[], extras: { queryParams: Record<string, string | null> }) {
    const merged = { ...this.route.current };
    for (const [key, value] of Object.entries(extras.queryParams)) {
      if (value === null) delete merged[key];
      else merged[key] = value;
    }
    this.route.setParams(merged);
    return Promise.resolve(true);
  }
}

async function createFixture(
  initialParams: Record<string, string>,
): Promise<{ fixture: ComponentFixture<ReportsPage>; httpMock: HttpTestingController; route: FakeActivatedRoute }> {
  const route = new FakeActivatedRoute(initialParams);
  const router = new FakeRouter(route);

  await TestBed.configureTestingModule({
    imports: [
      ReportsPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: ActivatedRoute, useValue: route },
      { provide: Router, useValue: router },
    ],
  }).compileComponents();

  const fixture = TestBed.createComponent(ReportsPage);
  const httpMock = TestBed.inject(HttpTestingController);
  return { fixture, httpMock, route };
}

describe('ReportsPage', () => {
  afterEach(() => {
    // per-test httpMock.verify() is called explicitly where a mock is created
  });

  it('fetches the workspace default currency and writes it into query params when absent', async () => {
    const { fixture, httpMock } = await createFixture({ preset: 'this_month' });
    fixture.detectChanges();

    httpMock.expectOne('/api/reports/default-currency').flush({ currency: 'USD' });
    await fixture.whenStable();

    httpMock.expectOne((r) => r.url === '/api/reports/category-breakdown').flush(BREAKDOWN_EMPTY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_EMPTY);
    await fixture.whenStable();

    const compiled = fixture.nativeElement as HTMLElement;
    const currencyInput = compiled.querySelector(
      '[data-testid="filter-currency"]',
    ) as HTMLInputElement;
    expect(currencyInput.value).toBe('USD');
    httpMock.verify();
  });

  it('does not fetch default currency when it is already present in the URL', async () => {
    const { fixture, httpMock } = await createFixture({
      preset: 'this_month',
      currency: 'EUR',
    });
    fixture.detectChanges();

    httpMock.expectOne((r) => r.url === '/api/reports/category-breakdown').flush(BREAKDOWN_EMPTY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_EMPTY);
    await fixture.whenStable();

    httpMock.verify();
  });

  it('shows ui-empty-state when breakdown and trend are both all-zero (D92)', async () => {
    const { fixture, httpMock } = await createFixture({
      preset: 'this_month',
      currency: 'EUR',
    });
    fixture.detectChanges();

    httpMock.expectOne((r) => r.url === '/api/reports/category-breakdown').flush(BREAKDOWN_EMPTY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_EMPTY);
    await fixture.whenStable();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('[data-testid="reports-empty"]')).toBeTruthy();
    expect(compiled.querySelector('[data-testid="reports-breakdown-placeholder"]')).toBeFalsy();
    httpMock.verify();
  });

  it('shows the chart placeholder slots when there is activity', async () => {
    const { fixture, httpMock } = await createFixture({
      preset: 'this_month',
      currency: 'EUR',
    });
    fixture.detectChanges();

    httpMock
      .expectOne((r) => r.url === '/api/reports/category-breakdown')
      .flush(BREAKDOWN_WITH_ACTIVITY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_WITH_ACTIVITY);
    await fixture.whenStable();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('[data-testid="reports-breakdown-placeholder"]')).toBeTruthy();
    expect(compiled.querySelector('[data-testid="reports-trend-placeholder"]')).toBeTruthy();
    expect(compiled.querySelector('[data-testid="reports-empty"]')).toBeFalsy();
    httpMock.verify();
  });

  it('round-trips a preset change through the URL query params and reloads', async () => {
    const { fixture, httpMock, route } = await createFixture({
      preset: 'this_month',
      currency: 'EUR',
    });
    fixture.detectChanges();

    httpMock.expectOne((r) => r.url === '/api/reports/category-breakdown').flush(BREAKDOWN_EMPTY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_EMPTY);
    await fixture.whenStable();

    const compiled = fixture.nativeElement as HTMLElement;
    const presetSelect = compiled.querySelector(
      '[data-testid="filter-preset"]',
    ) as HTMLSelectElement;
    presetSelect.value = 'year_to_date';
    presetSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    await fixture.whenStable();

    expect(route.current['preset']).toBe('year_to_date');

    httpMock.expectOne((r) => r.url === '/api/reports/category-breakdown').flush(BREAKDOWN_EMPTY);
    httpMock.expectOne((r) => r.url === '/api/reports/trend').flush(TREND_EMPTY);
    await fixture.whenStable();

    httpMock.verify();
  });

  it('does not call the API when preset=custom and the custom range is incomplete', async () => {
    const { fixture, httpMock } = await createFixture({
      preset: 'custom',
      currency: 'EUR',
    });
    fixture.detectChanges();
    await fixture.whenStable();

    httpMock.verify();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('[data-testid="reports-empty"]')).toBeFalsy();
  });
});
