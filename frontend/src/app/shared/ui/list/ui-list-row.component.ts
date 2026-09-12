import { Component } from '@angular/core';

/**
 * Design D57/D60/D63 — a card at base width, a table-like row at `md`.
 * No inputs beyond content projection: it merely renders the real `<li>`
 * that `ui-list-cell` children compose inside (D58's forwarding rule
 * only applies where a spec observes the element; none selects a row by
 * tag or testid).
 */
@Component({
  selector: 'ui-list-row',
  templateUrl: './ui-list-row.component.html',
})
export class UiListRowComponent {}
