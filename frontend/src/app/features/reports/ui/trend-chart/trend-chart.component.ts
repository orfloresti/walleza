import { Component, computed, input } from '@angular/core';
import { extent } from 'd3-array';
import { scaleLinear, scaleUtc } from 'd3-scale';
import { line as d3Line } from 'd3-shape';

import { ReportBucket, TrendPoint } from '../../data/reports.service';

/** One renderable bucket — all geometry pre-computed as plain numbers,
 * design D90: D3 is pure math, Angular's `@for` writes the DOM. */
export interface TrendBar {
  key: string;
  total: number;
  partial: boolean;
  x: number;
  width: number;
  /** Bar height in pixels, `0` for a `$0` bucket (never NaN). */
  height: number;
  /** SVG `y` of the bar's top edge (bars grow up from the baseline). */
  y: number;
}

/** One point on the line-chart path (`day`/`week` buckets). */
export interface TrendLinePoint {
  key: string;
  total: number;
  partial: boolean;
  x: number;
  y: number;
}

const CHART_WIDTH = 480;
const CHART_HEIGHT = 220;
const BASELINE_Y = CHART_HEIGHT;

/**
 * Trend chart for `GET /api/reports/trend` (design D91): a bar chart for
 * `month`/`year` buckets (each bucket is a discrete, comparable period —
 * bars read clearer for "how much did I spend each month"), a line chart
 * for `day`/`week` buckets (many more points, a continuous trend reads
 * clearer than dozens of thin bars). Both branches are pure D3 math
 * (`scaleLinear`/`scaleUtc`/`d3-shape`'s `line()` generator, design D90)
 * feeding an Angular template — no `d3-selection`, no DOM writes from D3.
 *
 * Design D84: a `partial: true` bucket (only partially inside the
 * requested range) is visually distinguished — a `data-partial="true"`
 * attribute plus a dedicated CSS class — never silently rendered the same
 * as a complete bucket.
 *
 * Design D92: the caller has already proven non-empty, non-all-zero data;
 * a single-bucket or `$0`-bucket series must still render without a
 * zero-width domain crash (`domain([0, max(values) || 1])`).
 */
@Component({
  selector: 'app-trend-chart',
  templateUrl: './trend-chart.component.html',
})
export class TrendChartComponent {
  readonly data = input.required<{ bucket: ReportBucket; points: TrendPoint[] }>();

  protected readonly chartWidth = CHART_WIDTH;
  protected readonly chartHeight = CHART_HEIGHT;

  /** `day`/`week` render as a line; `month`/`year` render as bars. */
  protected readonly isLineChart = computed(() => {
    const bucket = this.data().bucket;
    return bucket === 'day' || bucket === 'week';
  });

  private readonly maxTotal = computed(() => {
    const totals = this.data().points.map((point) => Number(point.total));
    return Math.max(0, ...totals) || 1;
  });

  protected readonly bars = computed<TrendBar[]>(() => {
    if (this.isLineChart()) return [];
    const points = this.data().points;
    const yScale = scaleLinear().domain([0, this.maxTotal()]).range([0, CHART_HEIGHT]);
    const bandWidth = CHART_WIDTH / Math.max(points.length, 1);
    const barWidth = bandWidth * 0.7;

    return points.map((point, index) => {
      const total = Number(point.total);
      const height = total > 0 ? yScale(total) : 0;
      return {
        key: point.bucket_start,
        total,
        partial: point.partial,
        x: index * bandWidth + (bandWidth - barWidth) / 2,
        width: barWidth,
        height,
        y: BASELINE_Y - height,
      };
    });
  });

  protected readonly linePoints = computed<TrendLinePoint[]>(() => {
    if (!this.isLineChart()) return [];
    const points = this.data().points;
    if (points.length === 0) return [];

    const dates = points.map((point) => new Date(point.bucket_start));
    const [minDate, maxDate] = extent(dates);
    const xScale = scaleUtc()
      .domain([minDate ?? dates[0], maxDate ?? dates[0]])
      .range([0, CHART_WIDTH]);
    const yScale = scaleLinear().domain([0, this.maxTotal()]).range([CHART_HEIGHT, 0]);

    return points.map((point) => ({
      key: point.bucket_start,
      total: Number(point.total),
      partial: point.partial,
      x: xScale(new Date(point.bucket_start)),
      y: yScale(Number(point.total)),
    }));
  });

  /** `d3-shape`'s `line()` generator computes the path `d` string as pure
   * math from `linePoints()` — Angular binds it once onto a single
   * `<path>`, no `d3-selection` involved. */
  protected readonly linePath = computed<string | null>(() => {
    const points = this.linePoints();
    if (points.length === 0) return null;
    const generator = d3Line<TrendLinePoint>()
      .x((point) => point.x)
      .y((point) => point.y);
    return generator(points);
  });
}
