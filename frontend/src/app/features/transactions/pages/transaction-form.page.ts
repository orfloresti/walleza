import { Component, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import {
  TransactionCreate,
  TransactionType,
  TransactionUpdate,
  TransactionsService,
} from '../data/transactions.service';
import {
  SplitAllocationRowsComponent,
  SplitRowValue,
} from '../ui/split-allocation-rows/split-allocation-rows.component';
import {
  SplitMismatchError,
  parseSplitMismatchError,
} from '../ui/split-allocation-rows/split-mismatch-error';
import { ReceiptUploadComponent } from '../ui/receipt-upload/receipt-upload.component';

/**
 * Create/edit transaction form (Phase 2 PR6 task 7.3, PR6b tasks 8.1/
 * 8.2): account, amount, date, notes, is_refund, checked, type, an
 * inline split-allocation editor (`ui/split-allocation-rows`), and a
 * receipt-photo picker (`ui/receipt-upload`).
 *
 * Design D24's save pipeline: ① `POST`/`PATCH /api/transactions`
 * (`splits`, when the editor holds at least one row, travels INLINE in
 * this SAME request body — design's own "splits are inline in the
 * transaction payload, never a separate sub-resource" — there is no
 * separate splits-saving step); ② only if a file is attached, once step
 * ① resolves and a transaction id exists, request a presigned upload
 * URL; ③ POST directly to S3; ④ confirm. Steps ②-④ are entirely owned
 * by `ReceiptUploadComponent.uploadIfSelected(transactionId)`, invoked
 * here immediately after step ①'s own HTTP call resolves — photo-first
 * is impossible by construction, exactly as D24 intends, since no
 * transaction id exists before step ①.
 *
 * Omitting `splits` entirely (the key itself) when the editor holds zero
 * rows preserves PR6's exact wire body for the basic case (design D21:
 * zero lines is legal, "uncategorized"; leaving `splits` out of a
 * `PATCH` body leaves any existing splits untouched server-side unless
 * `amount` changes, in which case the server independently re-validates
 * them and 422s if they no longer sum correctly).
 *
 * A 422 on the create/update call is inspected for a split-sum mismatch
 * (design D33; see `split-mismatch-error.ts` for why the ACTUAL backend
 * response is a prose `detail` string, not the structured
 * `expected_total`/`allocated_total` JSON fields design D33 describes)
 * and, when found, routed to the split editor's own `mismatchError`
 * input instead of the generic `errorKey` banner — the numbers rendered
 * are always the server's own, never client-computed.
 *
 * A `:id` route param switches the form into edit mode (`transactions.
 * routes.ts`'s `:id/edit` route); its absence (the `new` route) means
 * create mode. Money is kept as a raw `string` end-to-end — the amount
 * field's value is never parsed into a JS number (design D19).
 */
@Component({
  selector: 'app-transaction-form-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    SplitAllocationRowsComponent,
    ReceiptUploadComponent,
  ],
  template: `
    <section>
      <h1>
        {{ (isEditMode() ? 'transactions.editTitle' : 'transactions.createTitle') | transloco }}
      </h1>

      @if (loading()) {
        <p>{{ 'transactions.loading' | transloco }}</p>
      } @else {
        <form (ngSubmit)="save()">
          <label>
            {{ 'transactions.account' | transloco }}
            <select
              name="accountId"
              required
              data-testid="transaction-account-select"
              [ngModel]="accountId()"
              (ngModelChange)="accountId.set($event)"
            >
              <option value="">{{ 'transactions.selectAccount' | transloco }}</option>
              @for (account of accounts(); track account.id) {
                <option [value]="account.id">{{ account.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'transactions.type' | transloco }}
            <select
              name="type"
              data-testid="transaction-type-select"
              [ngModel]="type()"
              (ngModelChange)="type.set($event)"
            >
              <option value="expense">{{ 'transactions.expense' | transloco }}</option>
              <option value="income">{{ 'transactions.income' | transloco }}</option>
            </select>
          </label>

          <label>
            {{ 'transactions.amount' | transloco }}
            <input
              type="text"
              name="amount"
              required
              data-testid="transaction-amount-input"
              [ngModel]="amount()"
              (ngModelChange)="amount.set($event)"
            />
          </label>

          <label>
            {{ 'transactions.date' | transloco }}
            <input
              type="date"
              name="occurredOn"
              required
              data-testid="transaction-date-input"
              [ngModel]="occurredOn()"
              (ngModelChange)="occurredOn.set($event)"
            />
          </label>

          <label>
            {{ 'transactions.notes' | transloco }}
            <input
              type="text"
              name="notes"
              [ngModel]="notes()"
              (ngModelChange)="notes.set($event)"
            />
          </label>

          <label>
            <input
              type="checkbox"
              name="isRefund"
              [ngModel]="isRefund()"
              (ngModelChange)="isRefund.set($event)"
            />
            {{ 'transactions.isRefund' | transloco }}
          </label>

          <label>
            <input
              type="checkbox"
              name="checked"
              [ngModel]="checked()"
              (ngModelChange)="checked.set($event)"
            />
            {{ 'transactions.checked' | transloco }}
          </label>

          <app-split-allocation-rows
            [categories]="categories()"
            [(rows)]="splitRows"
            [mismatchError]="splitMismatchError()"
          />

          <app-receipt-upload />

          <button type="submit">
            {{ (isEditMode() ? 'transactions.save' : 'transactions.create') | transloco }}
          </button>
        </form>
      }

      @if (errorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
    </section>
  `,
})
export class TransactionFormPage {
  private readonly transactionsService = inject(TransactionsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  private readonly receiptUpload = viewChild(ReceiptUploadComponent);

  protected readonly transactionId = signal<string | null>(null);
  protected readonly isEditMode = signal(false);
  protected readonly loading = signal(true);
  protected readonly errorKey = signal<string | null>(null);

  protected readonly accountId = signal('');
  protected readonly type = signal<TransactionType>('expense');
  protected readonly amount = signal('');
  protected readonly occurredOn = signal('');
  protected readonly notes = signal('');
  protected readonly isRefund = signal(false);
  protected readonly checked = signal(false);

  /** The split-allocation editor's current row set (design D21/PR6b) —
   * two-way bound (`[(rows)]`) to `app-split-allocation-rows`. */
  protected readonly splitRows = signal<SplitRowValue[]>([]);
  /** Server-authoritative split-sum mismatch feedback (design D33), set
   * only when a 422 on save is recognized as a split-sum error (see
   * `split-mismatch-error.ts`); `null` otherwise. */
  protected readonly splitMismatchError = signal<SplitMismatchError | null>(null);

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.transactionId.set(id);
      this.isEditMode.set(true);
      this.loadExisting(id);
    } else {
      this.loading.set(false);
    }
  }

  private loadExisting(id: string): void {
    this.loading.set(true);
    this.transactionsService.getTransaction(id).subscribe({
      next: (transaction) => {
        this.accountId.set(transaction.account_id);
        this.type.set(transaction.type);
        this.amount.set(transaction.amount);
        this.occurredOn.set(transaction.occurred_on);
        this.notes.set(transaction.notes ?? '');
        this.isRefund.set(transaction.is_refund);
        this.checked.set(transaction.checked);
        // Seed the split editor with the transaction's CURRENT split
        // snapshot (design D22) — dropping each line's own `id`, since a
        // save() re-submits the whole set as `SplitInput` (no `id`
        // field); the server assigns fresh ids on `replace_splits`.
        this.splitRows.set(
          transaction.splits.map((split) => ({
            category_id: split.category_id,
            amount: split.amount,
          })),
        );
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.errorKey.set('transactions.loadError');
      },
    });
  }

  /**
   * Design D24's step ① — a single `POST` (create) or `PATCH` (edit),
   * with the split editor's rows travelling INLINE in that same body
   * (never a separate call). Once step ① resolves, steps ②-④ (the
   * photo pipeline) run through `ReceiptUploadComponent.uploadIfSelected`
   * — a no-op when no file was attached.
   */
  protected save(): void {
    this.errorKey.set(null);
    this.splitMismatchError.set(null);

    // Money and split amounts travel as the raw strings the form fields
    // hold — never parsed into a JS number anywhere in this round trip
    // (design D19).
    const body: TransactionCreate | TransactionUpdate = {
      account_id: this.accountId(),
      type: this.type(),
      amount: this.amount(),
      occurred_on: this.occurredOn(),
      notes: this.notes() || null,
      is_refund: this.isRefund(),
      checked: this.checked(),
    };

    // Omitting the `splits` key entirely when the editor holds zero rows
    // preserves the exact basic-case wire body PR6 already shipped
    // (design D21: zero lines is legal, "uncategorized"). A non-empty
    // row set is sent verbatim — the server, never this form, is the
    // sole authority on whether it sums to `amount` (design D22/D33).
    const rows = this.splitRows();
    if (rows.length > 0) {
      body.splits = rows.map((row) => ({ category_id: row.category_id, amount: row.amount }));
    }

    const id = this.transactionId();
    const request =
      this.isEditMode() && id
        ? this.transactionsService.updateTransaction(id, body)
        : this.transactionsService.createTransaction(body as TransactionCreate);

    request.subscribe({
      next: (transaction) => {
        // Design D24 steps ②-④, run only now that a transaction id
        // exists to authorize the presign against. Switching into edit
        // mode with the newly created id BEFORE this call means a retry
        // after a photo-upload failure re-submits as a PATCH, never a
        // second POST that would create a duplicate transaction.
        this.transactionId.set(transaction.id);
        this.isEditMode.set(true);

        this.receiptUpload()
          ?.uploadIfSelected(transaction.id)
          .subscribe({
            next: () => void this.router.navigateByUrl('/transactions'),
            error: () => {
              // The transaction itself is already saved; only the photo
              // upload failed. Stay on the page (now in edit mode, see
              // above) so the user can retry without losing their data.
              this.errorKey.set('transactions.photo.uploadError');
            },
          });
      },
      error: (err: HttpErrorResponse) => {
        if (err.status === 422) {
          const mismatch = parseSplitMismatchError(
            (err.error as { detail?: unknown } | null)?.detail,
          );
          if (mismatch) {
            this.splitMismatchError.set(mismatch);
            return;
          }
          this.errorKey.set('transactions.validationError');
          return;
        }
        this.errorKey.set('transactions.saveError');
      },
    });
  }
}
