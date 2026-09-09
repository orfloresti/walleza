import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../../accounts/data/accounts.service';
import { TransferFilters, TransfersService } from '../data/transfers.service';

/**
 * Transfers list (Phase 3 PR2, task 2.3): renders `GET /api/transfers`
 * with account (matches either side, design D39) and date-range filter
 * controls, an "add transfer" link, and a per-row delete action.
 *
 * Renders the P6-boundary copy (`transfers.balanceNotice`, design D34) so
 * a user moving money between accounts and seeing no balance change
 * does not mistake this deliberate deferral for a bug — balance netting
 * across all money-movement types is Phase 6's responsibility.
 *
 * Transfer visibility (design D38 — the double-INNER-JOIN over
 * `visible_accounts(scope)`) is enforced entirely server-side by
 * `visible_transfers(scope, ...)` — this page never filters or
 * re-derives visibility client-side, it only renders what
 * `GET /api/transfers` returns.
 */
@Component({
  selector: 'app-transfers-list-page',
  imports: [FormsModule, RouterLink, TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'transfers.title' | transloco }}</h1>

      <p data-testid="transfers-balance-notice">{{ 'transfers.balanceNotice' | transloco }}</p>

      <a routerLink="/transfers/new">{{ 'transfers.create' | transloco }}</a>

      <form data-testid="transfers-filters">
        <label>
          {{ 'transfers.filterAccount' | transloco }}
          <select
            name="filterAccount"
            data-testid="filter-account"
            [ngModel]="accountFilter()"
            (ngModelChange)="setAccountFilter($event)"
          >
            <option value="">{{ 'transfers.filterAll' | transloco }}</option>
            @for (account of accounts(); track account.id) {
              <option [value]="account.id">{{ account.name }}</option>
            }
          </select>
        </label>

        <label>
          {{ 'transfers.filterDateFrom' | transloco }}
          <input
            type="date"
            name="filterDateFrom"
            data-testid="filter-date-from"
            [ngModel]="dateFromFilter()"
            (ngModelChange)="setDateFromFilter($event)"
          />
        </label>

        <label>
          {{ 'transfers.filterDateTo' | transloco }}
          <input
            type="date"
            name="filterDateTo"
            data-testid="filter-date-to"
            [ngModel]="dateToFilter()"
            (ngModelChange)="setDateToFilter($event)"
          />
        </label>
      </form>

      @if (loading()) {
        <p>{{ 'transfers.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'transfers.loadError' | transloco }}</p>
      } @else {
        <ul data-testid="transfers-list">
          @for (transfer of transfers(); track transfer.id) {
            <li>
              <span>{{ transfer.occurred_on }}</span>
              <span data-testid="transfer-from">{{ accountName(transfer.from_account_id) }}</span>
              <span data-testid="transfer-from-amount">{{ transfer.from_amount }}</span>
              <span data-testid="transfer-to">{{ accountName(transfer.to_account_id) }}</span>
              <span data-testid="transfer-to-amount">{{ transfer.to_amount }}</span>
              @if (transfer.notes) {
                <span>{{ transfer.notes }}</span>
              }
              <button type="button" (click)="deleteTransfer(transfer.id)">
                {{ 'transfers.delete' | transloco }}
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
export class TransfersListPage {
  private readonly transfersService = inject(TransfersService);
  private readonly accountsService = inject(AccountsService);

  protected readonly transfers = this.transfersService.transfers;
  protected readonly accounts = this.accountsService.accounts;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly accountFilter = signal('');
  protected readonly dateFromFilter = signal('');
  protected readonly dateToFilter = signal('');

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

  protected setAccountFilter(value: string): void {
    this.accountFilter.set(value);
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

  private currentFilters(): TransferFilters {
    const filters: TransferFilters = {};
    if (this.accountFilter()) filters.account_id = this.accountFilter();
    if (this.dateFromFilter()) filters.date_from = this.dateFromFilter();
    if (this.dateToFilter()) filters.date_to = this.dateToFilter();
    return filters;
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.transfersService.listTransfers(this.currentFilters()).subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deleteTransfer(id: string): void {
    this.actionErrorKey.set(null);
    this.transfersService.deleteTransfer(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('transfers.deleteError'),
    });
  }
}
