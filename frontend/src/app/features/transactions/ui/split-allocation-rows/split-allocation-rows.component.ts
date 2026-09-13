import { Component, computed, input, model } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import { Category } from '../../../categories/data/categories.service';
import { UiAlertComponent } from '../../../../shared/ui/alert/ui-alert.component';
import { UiFieldComponent } from '../../../../shared/ui/field/ui-field.component';
import { UiInputComponent } from '../../../../shared/ui/input/ui-input.component';
import { UiSelectComponent, UiSelectOption } from '../../../../shared/ui/select/ui-select.component';
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
  imports: [TranslocoPipe, UiInputComponent, UiSelectComponent, UiAlertComponent, UiFieldComponent],
  template: `
    <fieldset data-testid="split-allocation-rows">
      <legend>{{ 'transactions.splits.title' | transloco }}</legend>

      @for (row of rows(); track $index) {
        <div data-testid="split-row">
          <ui-field labelKey="transactions.splits.category">
            <ui-select
              [testId]="'split-category-select-' + $index"
              [options]="categoryOptions()"
              placeholderKey="transactions.splits.selectCategory"
              [value]="row.category_id"
              (valueChange)="updateCategory($index, $event)"
            />
          </ui-field>

          <ui-field labelKey="transactions.splits.amount">
            <ui-input
              [testId]="'split-amount-input-' + $index"
              [value]="row.amount"
              (valueChange)="updateAmount($index, $event)"
            />
          </ui-field>

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
        <ui-alert testId="split-mismatch-error" [message]="error.rawMessage" />
        @if (error.expectedTotal !== null && error.allocatedTotal !== null) {
          <span data-testid="split-allocated-total">
            {{ 'transactions.splits.allocatedTotal' | transloco }}: {{ error.allocatedTotal }}
          </span>
          <span data-testid="split-expected-total">
            {{ 'transactions.splits.expectedTotal' | transloco }}: {{ error.expectedTotal }}
          </span>
        }
      }
    </fieldset>
  `,
})
export class SplitAllocationRowsComponent {
  readonly categories = input.required<Category[]>();
  readonly rows = model<SplitRowValue[]>([]);
  readonly mismatchError = input<SplitMismatchError | null>(null);

  protected readonly categoryOptions = computed<UiSelectOption[]>(() =>
    this.categories().map((category) => ({ value: category.id, label: category.name })),
  );

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
