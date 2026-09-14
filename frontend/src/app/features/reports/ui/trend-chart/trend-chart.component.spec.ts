/**
 * `TrendChartComponent` (Phase 6 PR2b, design D84/D90/D91/D92) — covers
 * the pure `bars()`/`linePoints()` geometry as their own testable units,
 * plus rendered SVG structure and the D84 `partial` visual distinction.
 * Never asserts on the `d3-shape` `line()`-generated `d` string contents
 * (opaque floats) — only that a `<path>` exists when a line is expected.
 */

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { ReportBucket, TrendPoint } from '../../data/reports.service';
import { TrendChartComponent } from './trend-chart.component';

function point(overrides: Partial<TrendPoint>): TrendPoint {
  return {
    bucket_start: '2026-09-01',
    bucket_end: '2026-09-30',
    partial: false,
    total: '10.00',
    ...overrides,
  };
}

async function createFixture(
  bucket: ReportBucket,
  points: TrendPoint[],
): Promise<ComponentFixture<TrendChartComponent>> {
  await TestBed.configureTestingModule({
    imports: [TrendChartComponent],
  }).compileComponents();

  const fixture = TestBed.createComponent(TrendChartComponent);
  fixture.componentRef.setInput('data', { bucket, points });
  fixture.detectChanges();
  return fixture;
}

describe('TrendChartComponent — bar mode (month/year buckets)', () => {
  it('computes bar heights proportional to each bucket total', async () => {
    const fixture = await createFixture('month', [
      point({ bucket_start: '2026-07-01', total: '50.00' }),
      point({ bucket_start: '2026-08-01', total: '100.00' }),
    ]);

    const bars = fixture.componentInstance['bars']();
    expect(bars).toHaveLength(2);
    expect(bars[1].height).toBeGreaterThan(bars[0].height);
  });

  it('renders a zero-height bar for a $0 bucket without NaN geometry (D92)', async () => {
    const fixture = await createFixture('month', [point({ total: '0' })]);

    const bars = fixture.componentInstance['bars']();
    expect(bars[0].height).toBe(0);
    expect(Number.isNaN(bars[0].height)).toBe(false);
  });

  it('renders a valid domain for a single-bucket series (D92)', async () => {
    const fixture = await createFixture('month', [point({ total: '25.00' })]);

    const bars = fixture.componentInstance['bars']();
    expect(bars).toHaveLength(1);
    expect(Number.isNaN(bars[0].height)).toBe(false);
  });

  it('visually distinguishes a partial bucket via a class and data attribute (D84)', async () => {
    const fixture = await createFixture('month', [
      point({ bucket_start: '2026-08-01', partial: false, total: '50.00' }),
      point({ bucket_start: '2026-09-01', partial: true, total: '20.00' }),
    ]);

    const compiled = fixture.nativeElement as HTMLElement;
    const rects = compiled.querySelectorAll('[data-testid="trend-bar"]');
    expect(rects).toHaveLength(2);
    expect(rects[0].classList.contains('trend-bar--partial')).toBe(false);
    expect(rects[1].classList.contains('trend-bar--partial')).toBe(true);
    expect(rects[1].getAttribute('data-partial')).toBe('true');
  });
});

describe('TrendChartComponent — line mode (day/week buckets)', () => {
  it('computes one line point per bucket with a valid x/y position', async () => {
    const fixture = await createFixture('day', [
      point({ bucket_start: '2026-09-01', total: '10.00' }),
      point({ bucket_start: '2026-09-02', total: '20.00' }),
    ]);

    const linePoints = fixture.componentInstance['linePoints']();
    expect(linePoints).toHaveLength(2);
    linePoints.forEach((p) => {
      expect(Number.isNaN(p.x)).toBe(false);
      expect(Number.isNaN(p.y)).toBe(false);
    });
  });

  it('renders a <path> and does not assert on its d-string contents', async () => {
    const fixture = await createFixture('week', [
      point({ bucket_start: '2026-09-01', total: '10.00' }),
      point({ bucket_start: '2026-09-08', total: '5.00' }),
    ]);

    const compiled = fixture.nativeElement as HTMLElement;
    const path = compiled.querySelector('[data-testid="trend-line"]');
    expect(path).toBeTruthy();
    expect(path?.getAttribute('d')).toBeTruthy();
  });

  it('visually distinguishes a partial point via a class and data attribute (D84)', async () => {
    const fixture = await createFixture('day', [
      point({ bucket_start: '2026-09-01', partial: false, total: '10.00' }),
      point({ bucket_start: '2026-09-02', partial: true, total: '20.00' }),
    ]);

    const compiled = fixture.nativeElement as HTMLElement;
    const circles = compiled.querySelectorAll('[data-testid="trend-point"]');
    expect(circles).toHaveLength(2);
    expect(circles[0].classList.contains('trend-point--partial')).toBe(false);
    expect(circles[1].classList.contains('trend-point--partial')).toBe(true);
  });

  it('renders a valid single-point line without NaN geometry (D92)', async () => {
    const fixture = await createFixture('day', [point({ total: '25.00' })]);

    const linePoints = fixture.componentInstance['linePoints']();
    expect(linePoints).toHaveLength(1);
    expect(Number.isNaN(linePoints[0].x)).toBe(false);
    expect(Number.isNaN(linePoints[0].y)).toBe(false);
  });
});
