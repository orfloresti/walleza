import { Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../../accounts/data/accounts.service';
import { RecurringService } from '../data/recurring.service';

/**
 * Recurring transactions list, ALSO the Subscriptions view (Phase 4 PR5,
 * task 5.2, design D56): renders `GET /api/recurring`, optionally preset
 * to `is_subscription=true` when this page is instantiated under the
 * `subscriptions` route (`recurring.routes.ts`'s static `data`). This is
 * the ENTIRE Subscriptions implementation — no second component, service,
 * or route family exists anywhere in this feature.
 *
 * Recurrence visibility is enforced entirely server-side by
 * `visible_recurring(scope, account_id, is_subscription)` — this page
 * never filters or re-derives visibility client-side.
 */
@Component({
  selector: 'app-recurring-list-page',
  imports: [RouterLink, TranslocoPipe],
  template: `
    <section>
      <h1>{{ (subscriptionsOnly() ? 'recurring.subscriptionsTitle' : 'recurring.title') | transloco }}</h1>

      <a routerLink="/recurring/new">{{ 'recurring.create' | transloco }}</a>

      @if (loading()) {
        <p>{{ 'recurring.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'recurring.loadError' | transloco }}</p>
      } @else {
        <ul data-testid="recurring-list">
          @for (recurring of recurringList(); track recurring.id) {
            <li>
              <span data-testid="recurring-account">{{ accountName(recurring.account_id) }}</span>
              <span data-testid="recurring-amount">{{ recurring.amount }}</span>
              <span data-testid="recurring-period">
                {{ recurring.repeat_every }} × {{ recurring.period }}
              </span>
              <span data-testid="recurring-next-date">{{ recurring.next_date }}</span>
              @if (recurring.is_subscription) {
                <span data-testid="recurring-subscription-badge">
                  {{ 'recurring.isSubscription' | transloco }}
                </span>
              }

              <a [routerLink]="['/recurring', recurring.id, 'edit']">
                {{ 'recurring.edit' | transloco }}
              </a>
              <button type="button" (click)="deleteRecurring(recurring.id)">
                {{ 'recurring.delete' | transloco }}
              </button>
            </li>
          }
        </ul>
      }

      @if (actionErrorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
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
