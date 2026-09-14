/**
 * `CategoryBreakdownChartComponent` (Phase 6 PR2b, design D90/D91/D92) —
 * covers pure `bars()` geometry as its own testable unit, plus the
 * rendered SVG structure. Never asserts on a D3-generated `d` string
 * (there isn't one here — bars are plain `<rect>` geometry).
 */

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { CategorySlice } from '../../data/reports.service';
import { CategoryBreakdownChartComponent } from './category-breakdown-chart.component';

function slice(overrides: Partial<CategorySlice>): CategorySlice {
  return {
    category_id: 'cat-1',
    name: 'Groceries',
    parent_id: null,
    own: '10.00',
    total: '10.00',
    ...overrides,
  };
}

async function createFixture(
  slices: CategorySlice[],
): Promise<ComponentFixture<CategoryBreakdownChartComponent>> {
  await TestBed.configureTestingModule({
    imports: [CategoryBreakdownChartComponent],
  }).compileComponents();

  const fixture = TestBed.createComponent(CategoryBreakdownChartComponent);
  fixture.componentRef.setInput('data', { slices });
  fixture.detectChanges();
  return fixture;
}

describe('CategoryBreakdownChartComponent', () => {
  it('computes bar widths proportional to each top-level category total', async () => {
    const fixture = await createFixture([
      slice({ category_id: 'cat-1', name: 'Groceries', total: '100.00' }),
      slice({ category_id: 'cat-2', name: 'Rent', total: '50.00' }),
    ]);

    const bars = fixture.componentInstance['bars']();
    expect(bars).toHaveLength(2);
    expect(bars[0].width).toBeGreaterThan(bars[1].width);
    expect(bars[1].width).toBeCloseTo(bars[0].width / 2, 1);
  });

  it('excludes child categories — only top-level slices become bars', async () => {
    const fixture = await createFixture([
      slice({ category_id: 'cat-1', name: 'Food', parent_id: null, total: '100.00' }),
      slice({ category_id: 'cat-1a', name: 'Groceries', parent_id: 'cat-1', total: '60.00' }),
    ]);

    const bars = fixture.componentInstance['bars']();
    expect(bars).toHaveLength(1);
    expect(bars[0].categoryId).toBe('cat-1');
  });

  it('renders a zero-width bar for a $0 category without NaN geometry (D92)', async () => {
    const fixture = await createFixture([
      slice({ category_id: 'cat-1', name: 'Groceries', total: '0' }),
    ]);

    const bars = fixture.componentInstance['bars']();
    expect(bars[0].width).toBe(0);
    expect(Number.isNaN(bars[0].width)).toBe(false);

    const compiled = fixture.nativeElement as HTMLElement;
    const rect = compiled.querySelector('[data-testid="breakdown-bar"]');
    expect(rect).toBeTruthy();
    expect(rect?.getAttribute('width')).toBe('0');
  });

  it('renders a valid domain for a single-category dataset (D92)', async () => {
    const fixture = await createFixture([
      slice({ category_id: 'cat-1', name: 'Only category', total: '25.00' }),
    ]);

    const bars = fixture.componentInstance['bars']();
    expect(bars).toHaveLength(1);
    expect(Number.isNaN(bars[0].width)).toBe(false);
    expect(bars[0].width).toBeGreaterThan(0);
  });

  it('renders one <rect> per top-level category in the SVG', async () => {
    const fixture = await createFixture([
      slice({ category_id: 'cat-1', name: 'Groceries', total: '100.00' }),
      slice({ category_id: 'cat-2', name: 'Rent', total: '50.00' }),
    ]);

    const compiled = fixture.nativeElement as HTMLElement;
    const rects = compiled.querySelectorAll('[data-testid="breakdown-bar"]');
    expect(rects).toHaveLength(2);
    expect(compiled.querySelector('[data-testid="breakdown-chart"]')).toBeTruthy();
  });
});
