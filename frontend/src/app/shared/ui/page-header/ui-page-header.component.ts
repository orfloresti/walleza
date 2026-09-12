import { Component, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

/**
 * Design D57/D63, spec `design-system` ("ui-card and ui-page-header
 * Structural Containers") — the consistent title/action-slot header used
 * by every feature list page. No `testId` input: none of the page-header
 * markup this phase replaces carries a `data-testid` today, and no
 * migrated spec queries a header by testid.
 */
@Component({
  selector: 'ui-page-header',
  imports: [TranslocoPipe],
  templateUrl: './ui-page-header.component.html',
})
export class UiPageHeaderComponent {
  readonly titleKey = input.required<string>();
}
