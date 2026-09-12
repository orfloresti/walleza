import { Component, computed, input, model } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import { FOCUS_RING } from '../ui-classes';

export interface UiSelectOption {
  readonly value: string;
  readonly label: string;
}

const BASE_CLASSES = 'border-border bg-surface text-on-surface';

/**
 * Design D57/D58 — a controlled component on `model<string>()`, the same
 * convention as `ui-input`/`split-allocation-rows.component.ts`'s
 * `[(rows)]`. Deliberately **owns its `<option>` elements** rather than
 * projecting page-authored ones: Angular's `NgSelectOption` injects its
 * parent `SelectControlValueAccessor` with `@Optional() @Host()`, and
 * `@Host()` does not cross a content-projection boundary, so a projected
 * `<option>` would never register in the select's `_optionMap` and
 * `writeValue` would silently fall through to `selectedIndex = -1`.
 * Owning the options keeps them real children of the real `<select>`, so
 * `firstSelect.options` and `'[data-testid="…"] option'` queries in
 * existing page specs keep working after migration.
 */
@Component({
  selector: 'ui-select',
  imports: [TranslocoPipe],
  templateUrl: './ui-select.component.html',
})
export class UiSelectComponent {
  readonly options = input.required<readonly UiSelectOption[]>();
  readonly value = model<string>('');
  readonly placeholderKey = input<string | null>(null);
  readonly name = input<string | null>(null);
  readonly required = input(false);
  readonly disabled = input(false);
  readonly testId = input<string | null>(null);

  protected readonly classes = computed(() => [BASE_CLASSES, FOCUS_RING].join(' '));

  protected onChange(event: Event): void {
    this.value.set((event.target as HTMLSelectElement).value);
  }
}
