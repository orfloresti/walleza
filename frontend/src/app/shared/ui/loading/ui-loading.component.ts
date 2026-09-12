import { Component, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

/**
 * Design D57/D63 — a live-region status message shown while a list
 * page's request is in flight, structurally distinct from the empty
 * state and the error alert (D64). `role="status"` lets assistive tech
 * announce it with no extra ARIA live-region wiring. `testId` forwards
 * onto the real `<p>` (D58).
 */
@Component({
  selector: 'ui-loading',
  imports: [TranslocoPipe],
  templateUrl: './ui-loading.component.html',
})
export class UiLoadingComponent {
  readonly messageKey = input.required<string>();
  readonly testId = input<string | null>(null);
}
