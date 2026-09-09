import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

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
  imports: [FormsModule, RouterLink, TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'transactions.title' | transloco }}</h1>

      <a routerLink="/transactions/new">{{ 'transactions.create' | transloco }}</a>

      <form data-testid="transactions-filters">
        <label>
          {{ 'transactions.filterAccount' | transloco }}
          <select
            name="filterAccount"
            data-testid="filter-account"
            [ngModel]="accountFilter()"
            (ngModelChange)="setAccountFilter($event)"
          >
            <option value="">{{ 'transactions.filterAll' | transloco }}</option>
            @for (account of accounts(); track account.id) {
              <option [value]="account.id">{{ account.name }}</option>
            }
          </select>
        </label>

        <label>
          {{ 'transactions.filterCategory' | transloco }}
          <select
            name="filterCategory"
            data-testid="filter-category"
            [ngModel]="categoryFilter()"
            (ngModelChange)="setCategoryFilter($event)"
          >
            <option value="">{{ 'transactions.filterAll' | transloco }}</option>
            @for (category of categories(); track category.id) {
              <option [value]="category.id">{{ category.name }}</option>
            }
          </select>
        </label>

        <label>
          {{ 'transactions.filterDateFrom' | transloco }}
          <input
            type="date"
            name="filterDateFrom"
            data-testid="filter-date-from"
            [ngModel]="dateFromFilter()"
            (ngModelChange)="setDateFromFilter($event)"
          />
        </label>

        <label>
          {{ 'transactions.filterDateTo' | transloco }}
          <input
            type="date"
            name="filterDateTo"
            data-testid="filter-date-to"
            [ngModel]="dateToFilter()"
            (ngModelChange)="setDateToFilter($event)"
          />
        </label>

        <label>
          {{ 'transactions.filterType' | transloco }}
          <select
            name="filterType"
            data-testid="filter-type"
            [ngModel]="typeFilter()"
            (ngModelChange)="setTypeFilter($event)"
          >
            <option value="">{{ 'transactions.filterAll' | transloco }}</option>
            <option value="expense">{{ 'transactions.expense' | transloco }}</option>
            <option value="income">{{ 'transactions.income' | transloco }}</option>
          </select>
        </label>
      </form>

      @if (loading()) {
        <p>{{ 'transactions.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'transactions.loadError' | transloco }}</p>
      } @else {
        <ul data-testid="transactions-list">
          @for (transaction of transactions(); track transaction.id) {
            <li>
              <span>{{ transaction.occurred_on }}</span>
              <span>{{ accountName(transaction.account_id) }}</span>
              <span data-testid="transaction-type">{{ transaction.type }}</span>
              <span data-testid="transaction-amount">{{ transaction.amount }}</span>
              @if (transaction.notes) {
                <span>{{ transaction.notes }}</span>
              }
              @if (transaction.is_refund) {
                <span data-testid="refund-badge">{{ 'transactions.refundBadge' | transloco }}</span>
              }
              @if (transaction.checked) {
                <span data-testid="checked-badge">{{ 'transactions.checkedBadge' | transloco }}</span>
              }
              <a [routerLink]="['/transactions', transaction.id, 'edit']">
                {{ 'transactions.edit' | transloco }}
              </a>
              <button type="button" (click)="deleteTransaction(transaction.id)">
                {{ 'transactions.delete' | transloco }}
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
export class TransactionsListPage {
  private readonly transactionsService = inject(TransactionsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);

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

  protected setTypeFilter(value: TransactionType | ''): void {
    this.typeFilter.set(value);
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
