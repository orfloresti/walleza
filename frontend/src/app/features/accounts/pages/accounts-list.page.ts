import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../data/accounts.service';

/**
 * Accounts list/CRUD view (Phase 1 PR4b, tasks 8.1/8.2): renders
 * `GET /api/accounts` (toggle between active and archived, task 8.1),
 * a create form covering name/currency/exchange_rate/initial_funds/
 * is_personal (task 8.2), and an inline archive action per row —
 * `PATCH { archived: true }`, never DELETE (there is no DELETE route,
 * design's Interfaces/Contracts table, decision 6). Deliberately
 * unpolished per the proposal: functionally correct, not styled, no
 * separate edit view (archiving is the only mutation this phase's UI
 * needs beyond create).
 *
 * Personal-account visibility (design D15/spec `account-visibility`) is
 * enforced entirely server-side by `visible_accounts(scope)` — this page
 * never filters or re-derives visibility client-side, it only renders
 * what `GET /api/accounts` returns and marks `is_personal` rows with a
 * badge so a shared vs. personal account is visually distinguishable.
 */
@Component({
  selector: 'app-accounts-list-page',
  imports: [FormsModule, TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'accounts.title' | transloco }}</h1>

      <label>
        <input
          type="checkbox"
          data-testid="show-archived-toggle"
          [checked]="showArchived()"
          (change)="toggleArchived()"
        />
        {{ 'accounts.showArchived' | transloco }}
      </label>

      @if (loading()) {
        <p>{{ 'accounts.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'accounts.loadError' | transloco }}</p>
      } @else {
        <ul data-testid="accounts-list">
          @for (account of accounts(); track account.id) {
            <li>
              <span>{{ account.name }}</span>
              <span>{{ account.currency }}</span>
              <span>{{ account.initial_funds }}</span>
              @if (account.is_personal) {
                <span data-testid="personal-badge">{{ 'accounts.personalBadge' | transloco }}</span>
              }
              @if (account.archived) {
                <span data-testid="archived-badge">{{ 'accounts.archivedBadge' | transloco }}</span>
              } @else {
                <button type="button" (click)="archiveAccount(account.id)">
                  {{ 'accounts.archive' | transloco }}
                </button>
              }
            </li>
          }
        </ul>
      }

      <form (ngSubmit)="createAccount()">
        <h2>{{ 'accounts.createTitle' | transloco }}</h2>

        <label>
          {{ 'accounts.name' | transloco }}
          <input
            type="text"
            name="name"
            required
            [ngModel]="name()"
            (ngModelChange)="name.set($event)"
          />
        </label>

        <label>
          {{ 'accounts.currency' | transloco }}
          <input
            type="text"
            name="currency"
            required
            maxlength="3"
            [ngModel]="currency()"
            (ngModelChange)="currency.set($event)"
          />
        </label>

        <label>
          {{ 'accounts.exchangeRate' | transloco }}
          <input
            type="text"
            name="exchangeRate"
            [ngModel]="exchangeRate()"
            (ngModelChange)="exchangeRate.set($event)"
          />
        </label>

        <label>
          {{ 'accounts.initialFunds' | transloco }}
          <input
            type="text"
            name="initialFunds"
            [ngModel]="initialFunds()"
            (ngModelChange)="initialFunds.set($event)"
          />
        </label>

        <label>
          <input
            type="checkbox"
            name="isPersonal"
            [ngModel]="isPersonal()"
            (ngModelChange)="isPersonal.set($event)"
          />
          {{ 'accounts.isPersonal' | transloco }}
        </label>

        <button type="submit">{{ 'accounts.create' | transloco }}</button>
      </form>

      @if (actionErrorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
    </section>
  `,
})
export class AccountsListPage {
  private readonly accountsService = inject(AccountsService);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly showArchived = signal(false);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly name = signal('');
  protected readonly currency = signal('');
  protected readonly exchangeRate = signal('1');
  protected readonly initialFunds = signal('0');
  protected readonly isPersonal = signal(false);

  constructor() {
    this.load();
  }

  protected toggleArchived(): void {
    this.showArchived.set(!this.showArchived());
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.accountsService.listAccounts(this.showArchived()).subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected createAccount(): void {
    this.actionErrorKey.set(null);
    this.accountsService
      .createAccount({
        name: this.name(),
        currency: this.currency().toUpperCase(),
        // Money fields travel as strings the whole way (design D19) —
        // exactly the form field's raw value, never parsed into a JS
        // number and written back, so precision is never at risk.
        exchange_rate: this.exchangeRate(),
        initial_funds: this.initialFunds(),
        is_personal: this.isPersonal(),
      })
      .subscribe({
        next: () => {
          this.name.set('');
          this.currency.set('');
          this.exchangeRate.set('1');
          this.initialFunds.set('0');
          this.isPersonal.set(false);
          this.load();
        },
        error: () => this.actionErrorKey.set('accounts.createError'),
      });
  }

  protected archiveAccount(id: string): void {
    this.actionErrorKey.set(null);
    this.accountsService.archiveAccount(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('accounts.archiveError'),
    });
  }
}
