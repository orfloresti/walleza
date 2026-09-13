import { Component, computed, inject, signal } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiBadgeComponent,
  UiButtonComponent,
  UiCardComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiInputComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import {
  TransactionFilters,
  TransactionType,
  TransactionsService,
} from '../data/transactions.service';

/**
 * Transactions feed (Phase 2 PR6, task 7.2): renders
 * `GET /api/transactions` as a WORKSPACE-WIDE feed (not nested per
 * account — design's legacy-screenshot-cited evidence) with filter
 * controls for account/category/date range/type (design's Filtered
 * Workspace Transaction Feed requirement), a link to create a new
 * transaction, and an edit link + delete action per row.
 *
 * Split-allocation and photo-thumbnail rendering are deliberately NOT
 * here — PR6b's job. This page renders every `TransactionOut` field the
 * BASIC case produces; a transaction's `splits` array is present on the
 * response (possibly empty) but not rendered by this PR.
 *
 * Transaction visibility (design D30 — inherited entirely from the
 * account's own visibility) is enforced entirely server-side by
 * `visible_transactions(scope, ...)` — this page never filters or
 * re-derives visibility client-side, it only renders what
 * `GET /api/transactions` returns.
 */
@Component({
  selector: 'app-transactions-list-page',
  imports: [
    TranslocoPipe,
    UiAlertComponent,
    UiBadgeComponent,
    UiButtonComponent,
    UiCardComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiInputComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-5xl px-4 py-6">
      <ui-page-header titleKey="transactions.title">
        <ui-button link="/transactions/new" variant="primary">
          {{ 'transactions.create' | transloco }}
        </ui-button>
      </ui-page-header>

      <ui-card>
        <form
          data-testid="transactions-filters"
          class="grid grid-cols-1 gap-3 md:grid-cols-5"
        >
          <ui-field labelKey="transactions.filterAccount">
            <ui-select
              name="filterAccount"
              testId="filter-account"
              [options]="accountOptions()"
              placeholderKey="transactions.filterAll"
              [value]="accountFilter()"
              (valueChange)="setAccountFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transactions.filterCategory">
            <ui-select
              name="filterCategory"
              testId="filter-category"
              [options]="categoryOptions()"
              placeholderKey="transactions.filterAll"
              [value]="categoryFilter()"
              (valueChange)="setCategoryFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transactions.filterDateFrom">
            <ui-input
              type="date"
              name="filterDateFrom"
              testId="filter-date-from"
              [value]="dateFromFilter()"
              (valueChange)="setDateFromFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transactions.filterDateTo">
            <ui-input
              type="date"
              name="filterDateTo"
              testId="filter-date-to"
              [value]="dateToFilter()"
              (valueChange)="setDateToFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transactions.filterType">
            <ui-select
              name="filterType"
              testId="filter-type"
              [options]="typeOptions()"
              placeholderKey="transactions.filterAll"
              [value]="typeFilter()"
              (valueChange)="setTypeFilter($event)"
            />
          </ui-field>
        </form>
      </ui-card>

      @if (loading()) {
        <ui-loading messageKey="transactions.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="transactions.loadError" />
      } @else if (transactions().length === 0) {
        <ui-empty-state
          testId="transactions-empty"
          titleKey="transactions.empty.title"
          messageKey="transactions.empty.body"
        >
          <ui-button link="/transactions/new" variant="primary">
            {{ 'transactions.create' | transloco }}
          </ui-button>
        </ui-empty-state>
      } @else {
        <ui-list testId="transactions-list">
          @for (transaction of transactions(); track transaction.id) {
            <ui-list-row>
              <ui-list-cell labelKey="transactions.filterDateFrom">
                <span>{{ transaction.occurred_on }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="transactions.filterAccount">
                <span>{{ accountName(transaction.account_id) }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="transactions.type">
                <span data-testid="transaction-type">{{ transaction.type }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="transactions.amount">
                <span data-testid="transaction-amount">{{ transaction.amount }}</span>
              </ui-list-cell>
              @if (transaction.notes) {
                <ui-list-cell>
                  <span>{{ transaction.notes }}</span>
                </ui-list-cell>
              }
              @if (transaction.is_refund) {
                <ui-badge variant="refund" testId="refund-badge">
                  {{ 'transactions.refundBadge' | transloco }}
                </ui-badge>
              }
              @if (transaction.checked) {
                <ui-badge variant="checked" testId="checked-badge">
                  {{ 'transactions.checkedBadge' | transloco }}
                </ui-badge>
              }
              <ui-list-cell class="md:ml-auto">
                <ui-button link="/transactions/{{ transaction.id }}/edit" variant="secondary" size="sm">
                  {{ 'transactions.edit' | transloco }}
                </ui-button>
                <ui-button variant="danger" size="sm" (click)="deleteTransaction(transaction.id)">
                  {{ 'transactions.delete' | transloco }}
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
export class TransactionsListPage {
  private readonly transactionsService = inject(TransactionsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly transloco = inject(TranslocoService);

  protected readonly transactions = this.transactionsService.transactions;
  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly accountFilter = signal('');
  protected readonly categoryFilter = signal('');
  protected readonly dateFromFilter = signal('');
  protected readonly dateToFilter = signal('');
  protected readonly typeFilter = signal<TransactionType | ''>('');

  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  protected readonly categoryOptions = computed<UiSelectOption[]>(() =>
    this.categories().map((c) => ({ value: c.id, label: c.name })),
  );

  protected readonly typeOptions = computed<UiSelectOption[]>(() => [
    { value: 'expense', label: this.transloco.translate('transactions.expense') },
    { value: 'income', label: this.transloco.translate('transactions.income') },
  ]);

  private readonly accountNameById = computed(() => {
    const map = new Map<string, string>();
    for (const account of this.accounts()) {
      map.set(account.id, account.name);
    }
    return map;
  });

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();
    this.load();
  }

  protected accountName(accountId: string): string {
    return this.accountNameById().get(accountId) ?? accountId;
  }

  protected setAccountFilter(value: string): void {
    this.accountFilter.set(value);
    this.load();
  }

  protected setCategoryFilter(value: string): void {
    this.categoryFilter.set(value);
    this.load();
  }

  protected setDateFromFilter(value: string): void {
    this.dateFromFilter.set(value);
    this.load();
  }

  protected setDateToFilter(value: string): void {
    this.dateToFilter.set(value);
    this.load();
  }

  protected setTypeFilter(value: string): void {
    this.typeFilter.set(value as TransactionType | '');
    this.load();
  }

  private currentFilters(): TransactionFilters {
    const filters: TransactionFilters = {};
    if (this.accountFilter()) filters.account_id = this.accountFilter();
    if (this.categoryFilter()) filters.category_id = this.categoryFilter();
    if (this.dateFromFilter()) filters.date_from = this.dateFromFilter();
    if (this.dateToFilter()) filters.date_to = this.dateToFilter();
    if (this.typeFilter()) filters.type = this.typeFilter() as TransactionType;
    return filters;
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.transactionsService.listTransactions(this.currentFilters()).subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deleteTransaction(id: string): void {
    this.actionErrorKey.set(null);
    this.transactionsService.deleteTransaction(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('transactions.deleteError'),
    });
  }
}
