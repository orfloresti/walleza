import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiBadgeComponent,
  UiButtonComponent,
  UiEmptyStateComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { RecurringService } from '../data/recurring.service';

/**
 * Recurring transactions list, ALSO the Subscriptions view (Phase 4 PR5,
 * task 5.2, design D56; migrated to the shared/ui kit in Phase 11 PR9,
 * task 11.2): renders `GET /api/recurring`, optionally preset to
 * `is_subscription=true` when this page is instantiated under the
 * `subscriptions` route (`recurring.routes.ts`'s static `data`). This is
 * the ENTIRE Subscriptions implementation — no second component, service,
 * or route family exists anywhere in this feature.
 *
 * Each row that is itself a subscription (`recurring.is_subscription`)
 * carries a `ui-badge variant="subscription"` marker — the kit's own
 * `subscription` badge variant (`ui-badge`'s 5-variant spec set), reused
 * here rather than introduced fresh.
 *
 * Recurrence visibility is enforced entirely server-side by
 * `visible_recurring(scope, account_id, is_subscription)` — this page
 * never filters or re-derives visibility client-side.
 */
@Component({
  selector: 'app-recurring-list-page',
  imports: [
    TranslocoPipe,
    UiAlertComponent,
    UiBadgeComponent,
    UiButtonComponent,
    UiEmptyStateComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-4xl px-4 py-6">
      <ui-page-header
        [titleKey]="subscriptionsOnly() ? 'recurring.subscriptionsTitle' : 'recurring.title'"
      >
        <ui-button link="/recurring/new" variant="primary">
          {{ 'recurring.create' | transloco }}
        </ui-button>
      </ui-page-header>

      @if (loading()) {
        <ui-loading messageKey="recurring.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="recurring.loadError" />
      } @else if (recurringList().length === 0) {
        <ui-empty-state
          testId="recurring-empty"
          titleKey="recurring.empty.title"
          messageKey="recurring.empty.body"
        >
          <ui-button link="/recurring/new" variant="primary">
            {{ 'recurring.create' | transloco }}
          </ui-button>
        </ui-empty-state>
      } @else {
        <ui-list testId="recurring-list">
          @for (recurring of recurringList(); track recurring.id) {
            <ui-list-row>
              <ui-list-cell labelKey="recurring.account">
                <span data-testid="recurring-account">{{ accountName(recurring.account_id) }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="recurring.amount">
                <span data-testid="recurring-amount">{{ recurring.amount }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="recurring.period">
                <span data-testid="recurring-period">
                  {{ recurring.repeat_every }} × {{ recurring.period }}
                </span>
              </ui-list-cell>
              <ui-list-cell labelKey="recurring.startsOn">
                <span data-testid="recurring-next-date">{{ recurring.next_date }}</span>
              </ui-list-cell>
              @if (recurring.is_subscription) {
                <ui-badge variant="subscription" testId="recurring-subscription-badge">
                  {{ 'recurring.isSubscription' | transloco }}
                </ui-badge>
              }

              <ui-list-cell class="md:ml-auto">
                <ui-button link="/recurring/{{ recurring.id }}/edit" variant="secondary" size="sm">
                  {{ 'recurring.edit' | transloco }}
                </ui-button>
                <ui-button variant="danger" size="sm" (click)="deleteRecurring(recurring.id)">
                  {{ 'recurring.delete' | transloco }}
                </ui-button>
              </ui-list-cell>
            </ui-list-row>
          }
        </ui-list>
      }

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
    </section>
  `,
})
export class RecurringListPage {
  private readonly recurringService = inject(RecurringService);
  private readonly accountsService = inject(AccountsService);
  private readonly route = inject(ActivatedRoute);

  protected readonly recurringList = this.recurringService.recurring;
  protected readonly accounts = this.accountsService.accounts;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  /** Whether this instance renders the Subscriptions route (design D56) —
   * read once from the route's static `data`, never mutated afterwards:
   * the preset is a property of WHICH route mounted this page, not of
   * user interaction. */
  protected readonly subscriptionsOnly = signal(
    this.route.snapshot.data['subscriptionsOnly'] === true,
  );

  private readonly accountNameById = computed(() => {
    const map = new Map<string, string>();
    for (const account of this.accounts()) {
      map.set(account.id, account.name);
    }
    return map;
  });

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.load();
  }

  protected accountName(accountId: string): string {
    return this.accountNameById().get(accountId) ?? accountId;
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    const filters = this.subscriptionsOnly() ? { is_subscription: true } : {};
    this.recurringService.listRecurring(filters).subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deleteRecurring(id: string): void {
    this.actionErrorKey.set(null);
    this.recurringService.deleteRecurring(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('recurring.deleteError'),
    });
  }
}
