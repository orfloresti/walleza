import { Component, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import { Category } from '../../../categories/data/categories.service';
import { SplitMismatchError } from './split-mismatch-error';

/** One editable split row — category + amount, both raw strings. Sent
 * inline as `SplitInput` (`transactions.service.ts`) on save; the server
 * is the sole authority on the sum invariant (design D21/D22) — this
 * component never validates or computes a running total itself. */
export interface SplitRowValue {
  category_id: string;
  amount: string;
}

/**
 * Inline split-allocation editor (Phase 2 PR6b, task 8.1): add/remove
 * rows, each with a category dropdown (populated from
 * `CategoriesService`) and a raw-string amount input. Renders the
 * server-authoritative mismatch feedback (design D33; see
 * `split-mismatch-error.ts` for why the real backend message is prose,
 * not a structured field pair) verbatim plus its best-effort-extracted
 * `expectedTotal`/`allocatedTotal` when both could be found — this
 * component never invents its own "remaining to allocate" arithmetic.
 *
 * `rows` is a `model()` (two-way signal binding, `[(rows)]="..."` from
 * the parent form) so the parent can read the current row set at save
 * time without this component owning any HTTP call of its own.
 */
@Component({
  selector: 'app-split-allocation-rows',
  imports: [FormsModule, TranslocoPipe],
  template: `
    <fieldset data-testid="split-allocation-rows">
      <legend>{{ 'transactions.splits.title' | transloco }}</legend>

      @for (row of rows(); track $index) {
        <div data-testid="split-row">
          <label>
            {{ 'transactions.splits.category' | transloco }}
            <select
              [attr.data-testid]="'split-category-select-' + $index"
              [ngModel]="row.category_id"
              [ngModelOptions]="{ standalone: true }"
              (ngModelChange)="updateCategory($index, $event)"
            >
              <option value="">{{ 'transactions.splits.selectCategory' | transloco }}</option>
              @for (category of categories(); track category.id) {
                <option [value]="category.id">{{ category.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'transactions.splits.amount' | transloco }}
            <input
              type="text"
              [attr.data-testid]="'split-amount-input-' + $index"
              [ngModel]="row.amount"
              [ngModelOptions]="{ standalone: true }"
              (ngModelChange)="updateAmount($index, $event)"
            />
          </label>

          <button
            type="button"
            data-testid="split-remove-row"
            (click)="removeRow($index)"
          >
            {{ 'transactions.splits.remove' | transloco }}
          </button>
        </div>
      }

      <button type="button" data-testid="split-add-row" (click)="addRow()">
        {{ 'transactions.splits.add' | transloco }}
      </button>

      @if (mismatchError(); as error) {
        <p role="alert" data-testid="split-mismatch-error">
          {{ error.rawMessage }}
          @if (error.expectedTotal !== null && error.allocatedTotal !== null) {
            <span data-testid="split-allocated-total">
              {{ 'transactions.splits.allocatedTotal' | transloco }}: {{ error.allocatedTotal }}
            </span>
            <span data-testid="split-expected-total">
              {{ 'transactions.splits.expectedTotal' | transloco }}: {{ error.expectedTotal }}
            </span>
          }
        </p>
      }
    </fieldset>
  `,
})
export class SplitAllocationRowsComponent {
  readonly categories = input.required<Category[]>();
  readonly rows = model<SplitRowValue[]>([]);
  readonly mismatchError = input<SplitMismatchError | null>(null);

  protected addRow(): void {
    this.rows.update((rows) => [...rows, { category_id: '', amount: '' }]);
  }

  protected removeRow(index: number): void {
    this.rows.update((rows) => rows.filter((_, i) => i !== index));
  }

  protected updateCategory(index: number, categoryId: string): void {
    this.rows.update((rows) =>
      rows.map((row, i) => (i === index ? { ...row, category_id: categoryId } : row)),
    );
  }

  protected updateAmount(index: number, amount: string): void {
    this.rows.update((rows) =>
      rows.map((row, i) => (i === index ? { ...row, amount } : row)),
    );
  }
}
