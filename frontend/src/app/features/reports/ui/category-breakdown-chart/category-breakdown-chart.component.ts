import { Component, computed, input } from '@angular/core';
import { scaleBand, scaleLinear } from 'd3-scale';

import { CategorySlice } from '../../data/reports.service';

/** One renderable bar — all geometry pre-computed as plain numbers, design
 * D90: D3 is a pure math library only, Angular's `@for` does 100% of the
 * DOM writing off this shape. */
export interface BreakdownBar {
  categoryId: string;
  name: string;
  own: number;
  total: number;
  /** SVG `y` of the bar's top edge. */
  y: number;
  /** Bar thickness (the band's computed height minus padding). */
  height: number;
  /** Bar length in pixels, `0` for a `$0` category (never NaN). */
  width: number;
}

const CHART_HEIGHT_PER_BAR = 32;
const CHART_WIDTH = 480;
const LABEL_WIDTH = 140;

/**
 * Horizontal bar chart for the category breakdown report (design D91).
 * A horizontal bar reads more clearly than a donut for a
 * parent/child-rollup dataset with an arbitrary, possibly long, category
 * count (design D91's own note: "bars when slice count > 8" — this
 * component always uses bars, never a donut, because every deployment
 * already has more than a handful of categories in practice and a single
 * chart shape keeps the component simple and consistently testable).
 *
 * Only TOP-LEVEL categories (`parent_id === null`) are rendered as bars —
 * a child's own spend is already folded into its parent's `total`
 * (design D80/D81), so plotting every slice would double-count visually.
 *
 * Design D92: the caller (`ReportsPage`) has already proven non-empty,
 * non-all-zero data before this component is constructed, so there is no
 * internal empty-state branch here — but a single top-level category, or
 * one with `total = 0`, must still render (zero-width bar), never throw
 * or produce NaN geometry (design D92's domain-floor rule).
 */
@Component({
  selector: 'app-category-breakdown-chart',
  templateUrl: './category-breakdown-chart.component.html',
})
export class CategoryBreakdownChartComponent {
  readonly data = input.required<{ slices: CategorySlice[] }>();

  protected readonly chartWidth = CHART_WIDTH;
  protected readonly plotWidth = CHART_WIDTH - LABEL_WIDTH;
  protected readonly labelWidth = LABEL_WIDTH;

  private readonly topLevelSlices = computed<CategorySlice[]>(() =>
    this.data().slices.filter((slice) => slice.parent_id === null),
  );

  protected readonly chartHeight = computed(
    () => Math.max(this.topLevelSlices().length, 1) * CHART_HEIGHT_PER_BAR,
  );

  /** Pure D3 math (design D90): `scaleBand` maps category index to a `y`
   * position, `scaleLinear` maps a dollar total to a pixel width. Both
   * scales are built from an already-non-empty, domain-floored input —
   * `domain([0, max || 1])` guarantees a valid scale even when every
   * top-level category is `$0` or there is exactly one category. */
  protected readonly bars = computed<BreakdownBar[]>(() => {
    const slices = this.topLevelSlices();
    const totals = slices.map((slice) => Number(slice.total));
    const maxTotal = Math.max(0, ...totals) || 1;

    const yScale = scaleBand<number>()
      .domain(slices.map((_, index) => index))
      .range([0, this.chartHeight()])
      .padding(0.2);

    const xScale = scaleLinear().domain([0, maxTotal]).range([0, this.plotWidth]);

    const bandwidth = yScale.bandwidth();

    return slices.map((slice, index) => {
      const total = Number(slice.total);
      return {
        categoryId: slice.category_id,
        name: slice.name,
        own: Number(slice.own),
        total,
        y: yScale(index) ?? index * CHART_HEIGHT_PER_BAR,
        height: bandwidth,
        width: total > 0 ? xScale(total) : 0,
      };
    });
  });
}
