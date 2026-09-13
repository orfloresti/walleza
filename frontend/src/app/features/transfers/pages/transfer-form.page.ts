import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiFieldComponent,
  UiInputComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
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
 *
 * Phase UI (PR7) — migrated to the `shared/ui/` kit. `FormsModule`
 * stays imported (design's Correction to revision 1): `(ngSubmit)` is
 * `NgForm`'s output and `transfer-form.page.spec.ts` drives submission
 * with `form.dispatchEvent(new Event('submit'))`. The server 422 detail
 * moves to `<ui-alert [message]="detail" testId="transfer-server-error" />`,
 * unchanged in kind (design's "reference migration", the verbatim-422
 * site) — task 8.5's pinned regression guard.
 */
@Component({
  selector: 'app-transfer-form-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiFieldComponent,
    UiInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-2xl px-4 py-6">
      <ui-page-header titleKey="transfers.createTitle" />

      @if (loading()) {
        <ui-loading messageKey="transfers.loading" />
      } @else {
        <form (ngSubmit)="save()" class="flex flex-col gap-3">
          <ui-field labelKey="transfers.fromAccount">
            <ui-select
              name="fromAccountId"
              [required]="true"
              testId="transfer-from-account-select"
              [options]="accountOptions()"
              placeholderKey="transfers.selectAccount"
              [(value)]="fromAccountId"
            />
          </ui-field>

          <ui-field labelKey="transfers.toAccount">
            <ui-select
              name="toAccountId"
              [required]="true"
              testId="transfer-to-account-select"
              [options]="accountOptions()"
              placeholderKey="transfers.selectAccount"
              [(value)]="toAccountId"
            />
          </ui-field>

          <ui-field labelKey="transfers.amount">
            <ui-input name="amount" [required]="true" testId="transfer-amount-input" [(value)]="amount" />
          </ui-field>

          <ui-field labelKey="transfers.date">
            <ui-input
              type="date"
              name="occurredOn"
              [required]="true"
              testId="transfer-date-input"
              [(value)]="occurredOn"
            />
          </ui-field>

          <ui-field labelKey="transfers.notes">
            <ui-input name="notes" [(value)]="notes" />
          </ui-field>

          <ui-button type="submit" variant="primary">{{ 'transfers.create' | transloco }}</ui-button>
        </form>
      }

      @if (errorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
      @if (serverErrorDetail(); as detail) {
        <ui-alert [message]="detail" testId="transfer-server-error" />
      }
    </section>
  `,
})
export class TransferFormPage {
  private readonly transfersService = inject(TransfersService);
  private readonly accountsService = inject(AccountsService);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;

  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

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
