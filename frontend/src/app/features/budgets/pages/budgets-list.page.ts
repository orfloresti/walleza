import { Component, computed, inject, signal } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiBadgeComponent,
  UiBadgeVariant,
  UiButtonComponent,
  UiEmptyStateComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import { BudgetStatus, BudgetsService } from '../data/budgets.service';

/** `progress.status` (design D75) maps 1:1 onto `ui-badge`'s matching
 * variant name — no separate mapping table is needed. */
const STATUS_BADGE_VARIANT: Record<BudgetStatus, UiBadgeVariant> = {
  on_track: 'on_track',
  near_limit: 'near_limit',
  over_budget: 'over_budget',
};

/**
 * Budgets list (Phase 5 PR2, task 2.3): renders `GET /api/budgets` — every
 * visible budget with its current-month progress computed server-side
 * (design D71-D78). This is the first feature built directly against
 * `shared/ui` from its first commit, so it follows `recurring-list.page.ts`'s
 * already-migrated shape verbatim rather than migrating anything.
 *
 * Each row shows category name, account (or "all accounts" when
 * `account_id` is null), limit/spent/remaining, and a `ui-badge` bound to
 * `progress.status` via one of the 3 new status variants Phase 5 added to
 * the kit (`on_track`/`near_limit`/`over_budget`).
 */
@Component({
  selector: 'app-budgets-list-page',
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
      <ui-page-header titleKey="budgets.title">
        <ui-button link="/budgets/new" variant="primary">
          {{ 'budgets.create' | transloco }}
        </ui-button>
      </ui-page-header>

      @if (loading()) {
        <ui-loading messageKey="budgets.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="budgets.loadError" />
      } @else if (budgetList().length === 0) {
        <ui-empty-state
          testId="budgets-empty"
          titleKey="budgets.empty.title"
          messageKey="budgets.empty.body"
        >
          <ui-button link="/budgets/new" variant="primary">
            {{ 'budgets.create' | transloco }}
          </ui-button>
        </ui-empty-state>
      } @else {
        <ui-list testId="budgets-list">
          @for (budget of budgetList(); track budget.id) {
            <ui-list-row>
              <ui-list-cell labelKey="budgets.category">
                <span data-testid="budget-category">{{ categoryName(budget.category_id) }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="budgets.account">
                <span data-testid="budget-account">{{ accountLabel(budget.account_id) }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="budgets.limit">
                <span data-testid="budget-limit">{{ budget.progress.limit }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="budgets.spent">
                <span data-testid="budget-spent">{{ budget.progress.spent }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="budgets.remaining">
                <span data-testid="budget-remaining">{{ budget.progress.remaining }}</span>
              </ui-list-cell>
              <ui-badge
                [variant]="statusVariant(budget.progress.status)"
                testId="budget-status-badge"
              >
                {{ 'budgets.status.' + budget.progress.status | transloco }}
              </ui-badge>

              <ui-list-cell class="md:ml-auto">
                <ui-button link="/budgets/{{ budget.id }}/edit" variant="secondary" size="sm">
                  {{ 'budgets.edit' | transloco }}
                </ui-button>
                <ui-button variant="danger" size="sm" (click)="deleteBudget(budget.id)">
                  {{ 'budgets.delete' | transloco }}
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
export class BudgetsListPage {
  private readonly budgetsService = inject(BudgetsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly transloco = inject(TranslocoService);

  protected readonly budgetList = this.budgetsService.budgets;
  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  private readonly accountNameById = computed(() => {
    const map = new Map<string, string>();
    for (const account of this.accounts()) {
      map.set(account.id, account.name);
    }
    return map;
  });

  private readonly categoryNameById = computed(() => {
    const map = new Map<string, string>();
    for (const category of this.categories()) {
      map.set(category.id, category.name);
    }
    return map;
  });

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();
    this.load();
  }

  protected categoryName(categoryId: string): string {
    return this.categoryNameById().get(categoryId) ?? categoryId;
  }

  /** `account_id === null` is a category-only budget spanning every
   * same-currency account (design D72). */
  protected accountLabel(accountId: string | null): string {
    if (accountId === null) return this.transloco.translate('budgets.allAccounts');
    return this.accountNameById().get(accountId) ?? accountId;
  }

  protected statusVariant(status: BudgetStatus): UiBadgeVariant {
    return STATUS_BADGE_VARIANT[status];
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.budgetsService.listBudgets().subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deleteBudget(id: string): void {
    this.actionErrorKey.set(null);
    this.budgetsService.deleteBudget(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('budgets.deleteError'),
    });
  }
}
