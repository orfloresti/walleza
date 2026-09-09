/**
 * `SplitAllocationRowsComponent` — Phase 2 PR6b (tasks 8.1/8.3). Renders
 * add/remove split rows and the server-authoritative 422 mismatch
 * feedback (design D33) directly from a `mismatchError` input — no HTTP
 * of its own, so this spec never touches `HttpTestingController`.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { Category } from '../../../categories/data/categories.service';
import { SplitAllocationRowsComponent, SplitRowValue } from './split-allocation-rows.component';
import { SplitMismatchError } from './split-mismatch-error';

const CATEGORY_GROCERIES: Category = {
  id: 'cat-1',
  workspace_id: 'ws-1',
  parent_id: null,
  name: 'Groceries',
  icon: null,
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const CATEGORY_TRANSPORT: Category = {
  ...CATEGORY_GROCERIES,
  id: 'cat-2',
  name: 'Transport',
};

const TRANSLATIONS = {
  transactions: {
    splits: {
      title: 'Split across categories',
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

/** A tiny host so `rows`/`mismatchError` can be driven as plain signal
 * inputs, matching how `TransactionFormPage` actually wires this
 * component (`[(rows)]`, `[mismatchError]`). */
@Component({
  imports: [SplitAllocationRowsComponent],
  template: `
    <app-split-allocation-rows
      [categories]="categories()"
      [(rows)]="rows"
      [mismatchError]="mismatchError()"
    />
  `,
})
class HostComponent {
  categories = signal<Category[]>([CATEGORY_GROCERIES, CATEGORY_TRANSPORT]);
  rows = signal<SplitRowValue[]>([]);
  mismatchError = signal<SplitMismatchError | null>(null);
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({
    imports: [
      HostComponent,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
  }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('SplitAllocationRowsComponent', () => {
  it('starts with zero rows and adds a row with an empty category/amount on "add split"', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('[data-testid="split-row"]').length).toBe(0);

    (el.querySelector('[data-testid="split-add-row"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(el.querySelectorAll('[data-testid="split-row"]').length).toBe(1);
    expect(fixture.componentInstance.rows()).toEqual([{ category_id: '', amount: '' }]);
  });

  it('populates the category dropdown from the categories input and removes a row', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.rows.set([
      { category_id: 'cat-1', amount: '60.00' },
      { category_id: 'cat-2', amount: '40.00' },
    ]);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const firstSelect = el.querySelector(
      '[data-testid="split-category-select-0"]',
    ) as HTMLSelectElement;
    expect(Array.from(firstSelect.options).map((o) => o.value)).toContain('cat-1');
    expect(Array.from(firstSelect.options).map((o) => o.value)).toContain('cat-2');

    (el.querySelector('[data-testid="split-remove-row"]') as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(fixture.componentInstance.rows()).toEqual([{ category_id: 'cat-2', amount: '40.00' }]);
  });

  it('renders the server-authoritative expected/allocated totals verbatim on a 422 mismatch (task focus)', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.mismatchError.set({
      rawMessage:
        'split amounts must sum exactly to the transaction amount (got 90.00, expected 100.00)',
      allocatedTotal: '90.00',
      expectedTotal: '100.00',
    });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const errorEl = el.querySelector('[data-testid="split-mismatch-error"]') as HTMLElement;
    expect(errorEl).not.toBeNull();
    // The exact server-provided numbers must appear verbatim — not a
    // client-computed remainder such as "10.00 left to allocate".
    expect(errorEl.textContent).toContain('90.00');
    expect(errorEl.textContent).toContain('100.00');
    expect(el.querySelector('[data-testid="split-allocated-total"]')?.textContent).toContain(
      '90.00',
    );
    expect(el.querySelector('[data-testid="split-expected-total"]')?.textContent).toContain(
      '100.00',
    );
  });

  it('renders no allocated/expected spans when only a raw message could be extracted', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.mismatchError.set({
      rawMessage: 'one or more split categories are not visible in this workspace',
      allocatedTotal: null,
      expectedTotal: null,
    });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="split-mismatch-error"]')?.textContent).toContain(
      'one or more split categories are not visible in this workspace',
    );
    expect(el.querySelector('[data-testid="split-allocated-total"]')).toBeNull();
    expect(el.querySelector('[data-testid="split-expected-total"]')).toBeNull();
  });
});
