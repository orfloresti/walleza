import { Component, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

/**
 * Design D57/D60/D63 — a labeled value cell. At base width the optional
 * `labelKey` renders a translated `md:hidden` mobile label beside the
 * projected value (a stacked card of bare values is unreadable without
 * it); at `md` the label is hidden by the CSS class alone and the row's
 * `md:flex-row` layout does the rest.
 *
 * Task 5.5 regression guard: the label's visibility is a CSS concern
 * (`md:hidden` in the class string) — never a structural one. Do not
 * replace the class with a breakpoint-signal `@if` that removes the span
 * from the DOM at desktop widths; jsdom cannot evaluate the media query
 * either way, so such a change would silently break real narrow-viewport
 * rendering while every existing spec still passes.
 */
@Component({
  selector: 'ui-list-cell',
  imports: [TranslocoPipe],
  templateUrl: './ui-list-cell.component.html',
})
export class UiListCellComponent {
  readonly labelKey = input<string | null>(null);
}
