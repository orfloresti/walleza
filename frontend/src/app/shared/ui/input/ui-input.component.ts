import { Component, computed, input, model } from '@angular/core';

import { FOCUS_RING } from '../ui-classes';

export type UiInputType = 'text' | 'number' | 'date';

const DEFAULT_CLASSES = 'border-border bg-surface text-on-surface';
const INVALID_CLASSES = 'border-danger bg-surface text-on-surface';

/**
 * Design D57 — a controlled component on `model<string>()`, the same
 * convention `split-allocation-rows.component.ts` already establishes
 * with `[(rows)]`. Deliberately not a `ControlValueAccessor`: nothing in
 * this codebase uses reactive forms, and every existing
 * `[ngModel]`/`(ngModelChange)` pair migrates as a mechanical 1:1 rename
 * to `[(value)]` (or `[value]`/`(valueChange)` when the page needs a side
 * effect on change).
 */
@Component({
  selector: 'ui-input',
  templateUrl: './ui-input.component.html',
})
export class UiInputComponent {
  readonly value = model<string>('');
  readonly type = input<UiInputType>('text');
  readonly name = input<string | null>(null);
  readonly required = input(false);
  readonly maxLength = input<number | null>(null);
  readonly disabled = input(false);
  readonly invalid = input(false);
  readonly testId = input<string | null>(null);

  protected readonly classes = computed(() =>
    [this.invalid() ? INVALID_CLASSES : DEFAULT_CLASSES, FOCUS_RING].join(' '),
  );

  protected onInput(event: Event): void {
    this.value.set((event.target as HTMLInputElement).value);
  }
}
