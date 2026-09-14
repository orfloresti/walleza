import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoService } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiCardComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiInputComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { DateRangePreset, resolvePreset } from '../data/date-range-presets';
import {
  CategoryBreakdown,
  ReportBucket,
  ReportsService,
  ReportType,
  Trend,
} from '../data/reports.service';
import { CategoryBreakdownChartComponent } from '../ui/category-breakdown-chart/category-breakdown-chart.component';
import { TrendChartComponent } from '../ui/trend-chart/trend-chart.component';

const PRESET_OPTIONS: readonly DateRangePreset[] = [
  'this_month',
  'last_3_months',
  'year_to_date',
  'custom',
];
const BUCKET_OPTIONS: readonly ReportBucket[] = ['day', 'week', 'month', 'year'];
const TYPE_OPTIONS: readonly ReportType[] = ['expense', 'income'];

/** URL query param keys (design D89) — a report view is bookmarkable /
 * shareable / back-button-friendly because ALL filter state round-trips
 * through these, never only component signals. */
const QUERY_PARAM = {
  preset: 'preset',
  from: 'from',
  to: 'to',
  bucket: 'bucket',
  currency: 'currency',
  type: 'type',
} as const;

/**
 * Reports page (Phase 6 PR2a, design D89) — the FIRST report-shaped page
 * in the app. One page hosts both the category-breakdown and trend
 * "charts" because they share a single filter bar (date-range preset +
 * custom range, bucket granularity, currency, type). Filter state is kept
 * in URL query params via the Router (not just component signals) so a
 * report view is bookmarkable/shareable/back-button-friendly.
 *
 * Date-range preset resolution happens CLIENT-SIDE
 * (`resolvePreset()`, design D89): the page always resolves a preset into
 * concrete `date_from`/`date_to` before calling the API — the backend
 * never sees a preset enum. Bucket granularity is a fully independent
 * control (design D83) — changing it never touches the date range.
 *
 * Empty-state detection (D92) happens HERE, above any chart construction
 * (this unit does not build charts — see the PR2b handoff note below):
 * `hasActivity` is computed purely from the fetched breakdown/trend
 * responses (every slice's `total` is `0` AND every trend point's `total`
 * is `0`), and `ui-empty-state` is shown instead of ever handing zero data
 * to a chart component.
 *
 * ---
 * ## Chart slots (design D91/D92, wired in PR2b)
 *
 * `CategoryBreakdownChartComponent`/`TrendChartComponent` (`features/
 * reports/ui/*`) render inside the SAME `hasActivity()` branch this page
 * already computes — the D92 empty-state guard is enforced here, above
 * chart construction, and is NOT duplicated inside either chart component
 * (each chart's own spec suite still tests its empty-state guard in
 * isolation, since the chart is also usable from other future call
 * sites).
 */
@Component({
  selector: 'app-reports-page',
  imports: [
    CategoryBreakdownChartComponent,
    TrendChartComponent,
    UiAlertComponent,
    UiCardComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-5xl px-4 py-6">
      <ui-page-header titleKey="reports.title" />

      <ui-card>
        <form data-testid="reports-filters" class="grid grid-cols-1 gap-3 md:grid-cols-4">
          <ui-field labelKey="reports.filterDateRange">
            <ui-select
              name="preset"
              testId="filter-preset"
              [options]="presetOptions()"
              [value]="preset()"
              (valueChange)="setPreset($event)"
            />
          </ui-field>

          @if (preset() === 'custom') {
            <ui-field labelKey="reports.filterCustomFrom">
              <ui-input
                type="date"
                name="customFrom"
                testId="filter-custom-from"
                [value]="customFrom()"
                (valueChange)="setCustomFrom($event)"
              />
            </ui-field>
            <ui-field labelKey="reports.filterCustomTo">
              <ui-input
                type="date"
                name="customTo"
                testId="filter-custom-to"
                [value]="customTo()"
                (valueChange)="setCustomTo($event)"
              />
            </ui-field>
          }

          <ui-field labelKey="reports.filterBucket">
            <ui-select
              name="bucket"
              testId="filter-bucket"
              [options]="bucketOptions()"
              [value]="bucket()"
              (valueChange)="setBucket($event)"
            />
          </ui-field>

          <ui-field labelKey="reports.filterCurrency">
            <ui-input
              name="currency"
              testId="filter-currency"
              [value]="currency()"
              (valueChange)="setCurrency($event)"
            />
          </ui-field>

          <ui-field labelKey="reports.filterType">
            <ui-select
              name="type"
              testId="filter-type"
              [options]="typeOptions()"
              [value]="type()"
              (valueChange)="setType($event)"
            />
          </ui-field>
        </form>
      </ui-card>

      @if (loading()) {
        <ui-loading messageKey="reports.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="reports.loadError" />
      } @else if (!hasData()) {
        <!-- No request has been made yet (e.g. an incomplete custom range) —
             render nothing below the filters rather than a misleading
             empty state. -->
      } @else if (!hasActivity()) {
        <ui-empty-state
          testId="reports-empty"
          titleKey="reports.empty.title"
          messageKey="reports.empty.body"
        />
      } @else {
        <ui-card>
          <app-category-breakdown-chart [data]="breakdown()!" />
        </ui-card>
        <ui-card>
          <app-trend-chart [data]="trend()!" />
        </ui-card>
      }
    </section>
  `,
})
export class ReportsPage {
  private readonly reportsService = inject(ReportsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly transloco = inject(TranslocoService);

  private readonly queryParamMap = toSignal(this.route.queryParamMap);

  protected readonly preset = computed<DateRangePreset>(() => {
    const value = this.queryParamMap()?.get(QUERY_PARAM.preset);
    return (PRESET_OPTIONS as readonly string[]).includes(value ?? '')
      ? (value as DateRangePreset)
      : 'this_month';
  });

  protected readonly customFrom = computed(
    () => this.queryParamMap()?.get(QUERY_PARAM.from) ?? '',
  );
  protected readonly customTo = computed(() => this.queryParamMap()?.get(QUERY_PARAM.to) ?? '');

  protected readonly bucket = computed<ReportBucket>(() => {
    const value = this.queryParamMap()?.get(QUERY_PARAM.bucket);
    return (BUCKET_OPTIONS as readonly string[]).includes(value ?? '')
      ? (value as ReportBucket)
      : 'month';
  });

  protected readonly type = computed<ReportType>(() => {
    const value = this.queryParamMap()?.get(QUERY_PARAM.type);
    return (TYPE_OPTIONS as readonly string[]).includes(value ?? '')
      ? (value as ReportType)
      : 'expense';
  });

  /** Resolved from the URL when present; otherwise fetched from
   * `GET /api/reports/default-currency` (design D89) once and written back
   * into the URL so the resolved currency itself becomes bookmarkable. */
  protected readonly currency = computed(() => this.queryParamMap()?.get(QUERY_PARAM.currency) ?? '');

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);

  protected readonly breakdown = signal<CategoryBreakdown | null>(null);
  protected readonly trend = signal<Trend | null>(null);

  /** True once both reports have been fetched for the current filters —
   * distinguishes "no request made yet" (e.g. an incomplete custom range)
   * from "request made, zero activity" (D92's actual empty state). */
  protected readonly hasData = computed(() => this.breakdown() !== null && this.trend() !== null);

  /** Empty-state detection (design D92) — computed BEFORE any chart is
   * constructed, purely from the resolved API responses: activity exists
   * only if at least one breakdown slice or trend bucket has a non-zero
   * total. */
  protected readonly hasActivity = computed(() => {
    const breakdown = this.breakdown();
    const trend = this.trend();
    if (!breakdown || !trend) return false;
    const breakdownHasActivity = breakdown.slices.some((slice) => Number(slice.total) !== 0);
    const trendHasActivity = trend.points.some((point) => Number(point.total) !== 0);
    return breakdownHasActivity || trendHasActivity;
  });

  protected readonly presetOptions = computed<UiSelectOption[]>(() =>
    PRESET_OPTIONS.map((value) => ({ value, label: this.presetLabel(value) })),
  );

  protected readonly bucketOptions = computed<UiSelectOption[]>(() =>
    BUCKET_OPTIONS.map((value) => ({ value, label: this.bucketLabel(value) })),
  );

  protected readonly typeOptions = computed<UiSelectOption[]>(() =>
    TYPE_OPTIONS.map((value) => ({ value, label: this.typeLabel(value) })),
  );

  constructor() {
    this.bootstrapCurrency();
    this.load();
  }

  private bootstrapCurrency(): void {
    if (this.currency()) return;
    this.reportsService.getDefaultCurrency().subscribe((result) => {
      if (result.currency && !this.currency()) {
        this.updateQueryParams({ [QUERY_PARAM.currency]: result.currency });
      }
    });
  }

  protected setPreset(value: string): void {
    const updates: Record<string, string | null> = { [QUERY_PARAM.preset]: value };
    if (value !== 'custom') {
      updates[QUERY_PARAM.from] = null;
      updates[QUERY_PARAM.to] = null;
    }
    this.updateQueryParams(updates);
  }

  protected setCustomFrom(value: string): void {
    this.updateQueryParams({ [QUERY_PARAM.from]: value });
  }

  protected setCustomTo(value: string): void {
    this.updateQueryParams({ [QUERY_PARAM.to]: value });
  }

  protected setBucket(value: string): void {
    this.updateQueryParams({ [QUERY_PARAM.bucket]: value });
  }

  protected setCurrency(value: string): void {
    this.updateQueryParams({ [QUERY_PARAM.currency]: value });
  }

  protected setType(value: string): void {
    this.updateQueryParams({ [QUERY_PARAM.type]: value });
  }

  private updateQueryParams(updates: Record<string, string | null>): void {
    this.router
      .navigate([], {
        relativeTo: this.route,
        queryParams: updates,
        queryParamsHandling: 'merge',
      })
      .then(() => this.load());
  }

  /** Resolves the current preset (or custom range) into concrete dates,
   * then loads both reports. A missing/incomplete custom range simply
   * skips loading (no request fired) rather than calling the API with
   * empty dates. */
  private load(): void {
    const currency = this.currency();
    if (!currency) {
      this.loading.set(false);
      this.breakdown.set(null);
      this.trend.set(null);
      return;
    }

    const range =
      this.preset() === 'custom'
        ? this.customFrom() && this.customTo()
          ? { date_from: this.customFrom(), date_to: this.customTo() }
          : null
        : resolvePreset(this.preset(), new Date());

    if (!range) {
      this.loading.set(false);
      this.breakdown.set(null);
      this.trend.set(null);
      return;
    }

    this.loading.set(true);
    this.loadError.set(false);

    let breakdownDone = false;
    let trendDone = false;
    const finish = () => {
      if (breakdownDone && trendDone) this.loading.set(false);
    };

    this.reportsService
      .getCategoryBreakdown({ ...range, currency, type: this.type() })
      .subscribe({
        next: (result) => {
          this.breakdown.set(result);
          breakdownDone = true;
          finish();
        },
        error: () => {
          this.loadError.set(true);
          this.loading.set(false);
        },
      });

    this.reportsService
      .getTrend({ ...range, currency, type: this.type(), bucket: this.bucket() })
      .subscribe({
        next: (result) => {
          this.trend.set(result);
          trendDone = true;
          finish();
        },
        error: () => {
          this.loadError.set(true);
          this.loading.set(false);
        },
      });
  }

  private presetLabel(preset: DateRangePreset): string {
    return this.transloco.translate(`reports.preset.${preset}`);
  }

  private bucketLabel(bucket: ReportBucket): string {
    return this.transloco.translate(`reports.bucket.${bucket}`);
  }

  private typeLabel(type: ReportType): string {
    return this.transloco.translate(`reports.type.${type}`);
  }
}
