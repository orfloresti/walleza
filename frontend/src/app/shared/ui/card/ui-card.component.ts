import { Component, input } from '@angular/core';

/**
 * Design D57/D63 — a real `<section>`, no variant styling: every consumer
 * (workspace summary, invite panel, filter panels) uses the same neutral
 * surface container. `testId` forwards onto the `<section>` itself (D58),
 * never a wrapper, so a page's existing `data-testid` keeps resolving to
 * the same semantic element after migration.
 */
@Component({
  selector: 'ui-card',
  templateUrl: './ui-card.component.html',
})
export class UiCardComponent {
  readonly testId = input<string | null>(null);
}
