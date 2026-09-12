import { Component, input, model } from '@angular/core';

/**
 * Design D57/D58 — a controlled component on `model<boolean>()`, the same
 * convention as `ui-input`/`ui-select`. The `(change)` handler MUST read
 * the DOM's *current* `.checked` value rather than assume a toggle of the
 * model's prior value: `accounts-list.page.spec.ts:128-131` dispatches a
 * bare `change` on `[data-testid="show-archived-toggle"]` without ever
 * setting `.checked`, so the payload at that moment is the checkbox's
 * unchanged `.checked` (`false`) — a naive `checked.set(!checked())`
 * would silently flip it to `true` and break that spec's
 * `archived=true` query-param assertion (migration invariant 3).
 */
@Component({
  selector: 'ui-checkbox',
  templateUrl: './ui-checkbox.component.html',
})
export class UiCheckboxComponent {
  readonly checked = model<boolean>(false);
  readonly name = input<string | null>(null);
  readonly disabled = input(false);
  readonly testId = input<string | null>(null);

  protected onChange(event: Event): void {
    this.checked.set((event.target as HTMLInputElement).checked);
  }
}
