import { Component, computed, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
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
 *
 * Phase UI (PR7) — migrated to the `shared/ui/` kit; this page IS the
 * design's own "reference migration" example (design's Reference
 * migration section), replicated verbatim here. The filter form's
 * account select uses `[options]="accountOptions()"` (a `computed()`
 * mapping `accounts()` to `UiSelectOption[]`) and keeps the exact
 * `[value]`/`(valueChange)` sequence the D34 reference migration
 * specifies — this is what task 8.2 pins as unmodified in the spec.
 */
@Component({
  selector: 'app-transfers-list-page',
  imports: [
    TranslocoPipe,
    UiAlertComponent,
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
      <ui-page-header titleKey="transfers.title">
        <ui-button link="/transfers/new" variant="primary">
          {{ 'transfers.create' | transloco }}
        </ui-button>
      </ui-page-header>

      <ui-alert
        variant="info"
        messageKey="transfers.balanceNotice"
        testId="transfers-balance-notice"
      />

      <ui-card>
        <form data-testid="transfers-filters" class="grid grid-cols-1 gap-3 md:grid-cols-3">
          <ui-field labelKey="transfers.filterAccount">
            <ui-select
              name="filterAccount"
              testId="filter-account"
              [options]="accountOptions()"
              placeholderKey="transfers.filterAll"
              [value]="accountFilter()"
              (valueChange)="setAccountFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transfers.filterDateFrom">
            <ui-input
              type="date"
              name="filterDateFrom"
              testId="filter-date-from"
              [value]="dateFromFilter()"
              (valueChange)="setDateFromFilter($event)"
            />
          </ui-field>
          <ui-field labelKey="transfers.filterDateTo">
            <ui-input
              type="date"
              name="filterDateTo"
              testId="filter-date-to"
              [value]="dateToFilter()"
              (valueChange)="setDateToFilter($event)"
            />
          </ui-field>
        </form>
      </ui-card>

      @if (loading()) {
        <ui-loading messageKey="transfers.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="transfers.loadError" />
      } @else if (transfers().length === 0) {
        <ui-empty-state
          testId="transfers-empty"
          titleKey="transfers.empty.title"
          messageKey="transfers.empty.body"
        >
          <ui-button link="/transfers/new" variant="primary">
            {{ 'transfers.create' | transloco }}
          </ui-button>
        </ui-empty-state>
      } @else {
        <ui-list testId="transfers-list">
          @for (transfer of transfers(); track transfer.id) {
            <ui-list-row>
              <ui-list-cell labelKey="transfers.date">
                <span>{{ transfer.occurred_on }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="transfers.fromAccount">
                <span data-testid="transfer-from">{{ accountName(transfer.from_account_id) }}</span>
                <span data-testid="transfer-from-amount">{{ transfer.from_amount }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="transfers.toAccount">
                <span data-testid="transfer-to">{{ accountName(transfer.to_account_id) }}</span>
                <span data-testid="transfer-to-amount">{{ transfer.to_amount }}</span>
              </ui-list-cell>
              @if (transfer.notes) {
                <ui-list-cell>
                  <span>{{ transfer.notes }}</span>
                </ui-list-cell>
              }
              <ui-list-cell class="md:ml-auto">
                <ui-button variant="danger" size="sm" (click)="deleteTransfer(transfer.id)">
                  {{ 'transfers.delete' | transloco }}
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

  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
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
