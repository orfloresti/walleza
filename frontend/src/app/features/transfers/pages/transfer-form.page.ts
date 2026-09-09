import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../../accounts/data/accounts.service';
import { TransferCreate, TransfersService } from '../data/transfers.service';

/**
 * Create-only transfer form (Phase 3 PR2, task 2.4): two account
 * selects (from/to), amount, date, notes. There is deliberately NO edit
 * mode and NO `:id` route param handling — design D43: a transfer has
 * no update endpoint at every layer, so this page has no reason to ever
 * branch on an id.
 *
 * Both account selects are populated from the SAME `AccountsService`
 * list — the backend independently enforces same-account rejection
 * (D42, `from_account_id <> to_account_id`) and both-sides-visible
 * (D38's double-INNER-JOIN) server-side; this form performs no
 * client-side duplicate of either rule beyond native `required` fields,
 * and simply renders whatever 422 the server returns verbatim (design
 * D44).
 *
 * `to_amount` is NEVER part of the submitted body (design D40/D44 — the
 * server always derives it); this page computes NO client-side
 * conversion preview — a live preview would be a second implementation
 * of currency arithmetic in JS, exactly what D19/D33 forbid.
 */
@Component({
  selector: 'app-transfer-form-page',
  imports: [FormsModule, TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'transfers.createTitle' | transloco }}</h1>

      @if (loading()) {
        <p>{{ 'transfers.loading' | transloco }}</p>
      } @else {
        <form (ngSubmit)="save()">
          <label>
            {{ 'transfers.fromAccount' | transloco }}
            <select
              name="fromAccountId"
              required
              data-testid="transfer-from-account-select"
              [ngModel]="fromAccountId()"
              (ngModelChange)="fromAccountId.set($event)"
            >
              <option value="">{{ 'transfers.selectAccount' | transloco }}</option>
              @for (account of accounts(); track account.id) {
                <option [value]="account.id">{{ account.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'transfers.toAccount' | transloco }}
            <select
              name="toAccountId"
              required
              data-testid="transfer-to-account-select"
              [ngModel]="toAccountId()"
              (ngModelChange)="toAccountId.set($event)"
            >
              <option value="">{{ 'transfers.selectAccount' | transloco }}</option>
              @for (account of accounts(); track account.id) {
                <option [value]="account.id">{{ account.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'transfers.amount' | transloco }}
            <input
              type="text"
              name="amount"
              required
              data-testid="transfer-amount-input"
              [ngModel]="amount()"
              (ngModelChange)="amount.set($event)"
            />
          </label>

          <label>
            {{ 'transfers.date' | transloco }}
            <input
              type="date"
              name="occurredOn"
              required
              data-testid="transfer-date-input"
              [ngModel]="occurredOn()"
              (ngModelChange)="occurredOn.set($event)"
            />
          </label>

          <label>
            {{ 'transfers.notes' | transloco }}
            <input
              type="text"
              name="notes"
              [ngModel]="notes()"
              (ngModelChange)="notes.set($event)"
            />
          </label>

          <button type="submit">{{ 'transfers.create' | transloco }}</button>
        </form>
      }

      @if (errorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
      @if (serverErrorDetail(); as detail) {
        <p role="alert" data-testid="transfer-server-error">{{ detail }}</p>
      }
    </section>
  `,
})
export class TransferFormPage {
  private readonly transfersService = inject(TransfersService);
  private readonly accountsService = inject(AccountsService);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;

  protected readonly loading = signal(true);
  protected readonly errorKey = signal<string | null>(null);
  /** The server's 422 `detail` rendered VERBATIM (design D44) — never
   * routed through `transloco`, never re-worded: this form performs no
   * client-side duplicate of the same-account or both-sides-visible
   * rules the backend already enforces, so the backend's own message is
   * the only explanation the user gets. */
  protected readonly serverErrorDetail = signal<string | null>(null);

  protected readonly fromAccountId = signal('');
  protected readonly toAccountId = signal('');
  protected readonly amount = signal('');
  protected readonly occurredOn = signal('');
  protected readonly notes = signal('');

  constructor() {
    this.accountsService.listAccounts().subscribe({
      next: () => this.loading.set(false),
      error: () => this.loading.set(false),
    });
  }

  /** `POST /api/transfers` — money travels as the raw string the amount
   * field holds, never parsed into a JS number (design D19). `body`
   * carries no `to_amount` key at all — `TransferCreate`'s type has no
   * such field, so there is nothing to accidentally send. */
  protected save(): void {
    this.errorKey.set(null);
    this.serverErrorDetail.set(null);

    const body: TransferCreate = {
      from_account_id: this.fromAccountId(),
      to_account_id: this.toAccountId(),
      from_amount: this.amount(),
      occurred_on: this.occurredOn(),
      notes: this.notes() || null,
    };

    this.transfersService.createTransfer(body).subscribe({
      next: () => void this.router.navigateByUrl('/transfers'),
      error: (err: HttpErrorResponse) => {
        if (err.status === 422) {
          const detail = (err.error as { detail?: unknown } | null)?.detail;
          if (typeof detail === 'string') {
            this.serverErrorDetail.set(detail);
            return;
          }
        }
        this.errorKey.set('transfers.saveError');
      },
    });
  }
}
