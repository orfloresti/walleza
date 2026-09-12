import { Component, input } from '@angular/core';

/**
 * Design D57/D60/D63 — the row-to-card list primitive. Flex, not Grid
 * (D60): row cell counts differ per feature, so a shared Grid primitive
 * would need a per-page column template — a second styling vocabulary
 * leaking back into pages. `testId` forwards onto the real `<ul>` (D58).
 */
@Component({
  selector: 'ui-list',
  templateUrl: './ui-list.component.html',
})
export class UiListComponent {
  readonly testId = input<string | null>(null);
}
