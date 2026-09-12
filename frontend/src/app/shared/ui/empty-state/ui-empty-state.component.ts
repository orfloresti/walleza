import { Component, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

/**
 * Design D57/D63/D64 — the third, structurally separate branch every list
 * page renders on a successful load with zero items (never a fallback
 * rendered inside `ui-list` or `ui-alert`). `testId` forwards onto the
 * real `<div>` (D58); `titleKey`/`messageKey` route through transloco
 * like every other kit copy. The optional projected content is the empty
 * state's primary action slot (e.g. "Add transfer").
 */
@Component({
  selector: 'ui-empty-state',
  imports: [TranslocoPipe],
  templateUrl: './ui-empty-state.component.html',
})
export class UiEmptyStateComponent {
  readonly titleKey = input.required<string>();
  readonly messageKey = input.required<string>();
  readonly testId = input<string | null>(null);
}
