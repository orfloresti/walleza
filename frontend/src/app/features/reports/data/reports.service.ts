import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** `bucket` param/field (design D83/D88) — fully independent of the date
 * range, validated server-side against this exact literal union. */
export type ReportBucket = 'day' | 'week' | 'month' | 'year';

/** `type` query param shared by `category-breakdown` and `trend`
 * (design D88's route table). */
export type ReportType = 'expense' | 'income';

/** `CategorySliceOut` (`backend/app/reports/schemas.py`) — `own`/`total`
 * kept SEPARATE per design D81, money kept as `string` end-to-end
 * (design D19), same convention `Budget`/`BudgetProgress` already use. */
export interface CategorySlice {
  category_id: string;
  name: string;
  parent_id: string | null;
  own: string;
  total: string;
}

/** `CategoryBreakdownOut` — `GET /api/reports/category-breakdown` response
 * shape. */
export interface CategoryBreakdown {
  currency: string;
  date_from: string;
  date_to: string;
  slices: CategorySlice[];
}

/** `TrendPointOut` — one densified bucket (design D84/D85). `partial=true`
 * flags a bucket only partially overlapping the requested range. */
export interface TrendPoint {
  bucket_start: string;
  bucket_end: string;
  partial: boolean;
  total: string;
}

/** `TrendOut` — `GET /api/reports/trend` response shape. */
export interface Trend {
  currency: string;
  bucket: ReportBucket;
  date_from: string;
  date_to: string;
  points: TrendPoint[];
}

/** `DefaultCurrencyOut` — `GET /api/reports/default-currency` response
 * shape; `currency` is `null` for a workspace with no accounts. */
export interface DefaultCurrency {
  currency: string | null;
}

/** Shared query params for `category-breakdown`/`trend` (design D88's
 * route table) — `date_from`/`date_to` are already-resolved concrete dates
 * (design D89: preset-to-range resolution happens client-side, the API
 * only ever receives resolved dates), never a preset enum. */
export interface CategoryBreakdownParams {
  date_from: string;
  date_to: string;
  currency: string;
  type?: ReportType;
  account_id?: string;
}

export interface TrendParams extends CategoryBreakdownParams {
  bucket: ReportBucket;
  category_id?: string;
}

export const REPORTS_ENDPOINT = '/api/reports';

/**
 * HTTP calls for the `report-category-breakdown`, `report-trend`, and
 * `report-default-currency` capabilities (design D88's route table). No
 * caching signal like `BudgetsService`/`CategoriesService`: reports are
 * filter-driven read views, not lists other pages reference by id, so the
 * page owns its own loading/result signals instead (design D89).
 */
@Injectable({ providedIn: 'root' })
export class ReportsService {
  private readonly http = inject(HttpClient);

  /** `GET /api/reports/category-breakdown`. */
  getCategoryBreakdown(params: CategoryBreakdownParams): Observable<CategoryBreakdown> {
    return this.http.get<CategoryBreakdown>(`${REPORTS_ENDPOINT}/category-breakdown`, {
      params: this.toHttpParams(params),
      withCredentials: true,
    });
  }

  /** `GET /api/reports/trend`. */
  getTrend(params: TrendParams): Observable<Trend> {
    return this.http.get<Trend>(`${REPORTS_ENDPOINT}/trend`, {
      params: this.toHttpParams(params),
      withCredentials: true,
    });
  }

  /** `GET /api/reports/default-currency` — used by the page only when
   * `currency` is absent from the URL query params (design D89). */
  getDefaultCurrency(): Observable<DefaultCurrency> {
    return this.http.get<DefaultCurrency>(`${REPORTS_ENDPOINT}/default-currency`, {
      withCredentials: true,
    });
  }

  private toHttpParams(params: object): HttpParams {
    let httpParams = new HttpParams();
    for (const [key, value] of Object.entries(params as Record<string, string | undefined>)) {
      if (value !== undefined && value !== null && value !== '') {
        httpParams = httpParams.set(key, value);
      }
    }
    return httpParams;
  }
}
