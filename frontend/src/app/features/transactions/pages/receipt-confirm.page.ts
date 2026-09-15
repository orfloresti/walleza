import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiBadgeComponent,
  UiButtonComponent,
  UiCardComponent,
  UiCheckboxComponent,
  UiFieldComponent,
  UiInputComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import { OcrCaptureHandoffService } from '../data/ocr-capture-handoff.service';
import {
  OcrExtraction,
  OcrStatus,
  TransactionCreate,
  TransactionType,
  TransactionsService,
} from '../data/transactions.service';

/** Design D134: a field with confidence below this threshold gets a
 * "check this" badge; a field absent from `field_confidence` renders as
 * an ordinary empty required field with no badge (the two cases must be
 * visually distinguishable). */
const OCR_LOW_CONFIDENCE_THRESHOLD = 80;

type ConfirmPhase = 'loading' | 'manual' | 'review' | 'processing';

/**
 * Confirm/review screen (design D134, Phase 9 Unit 9) at
 * `/transactions/{id}/confirm`. Reads `OcrCaptureHandoffService.consume()`
 * first (the fast path from Unit 8's same-session capture/upload/poll
 * flow); a `null` result (page refresh, direct navigation, or the
 * browser losing in-memory state) is a REAL case, handled by an
 * independent `getOcrStatus(id)` fetch — the same-shaped fallback the
 * hand-off service's own doc comment mandates, since a draft transaction
 * is invisible to the plain `GET /api/transactions/{id}` (design D120).
 *
 * The category field is ALWAYS empty and required — no auto-fill from
 * extraction, a hard product constraint (design D134 prose + this unit's
 * task list). An `extraction_failed` draft (or a non-terminal
 * `pending_ocr` result found on the independent fallback fetch — the
 * confirm endpoint per Unit 4's implementation can only transition an
 * `extracted`/`extraction_failed` draft, never `pending_ocr` directly)
 * renders the SAME form with every field blank/manual, the photo still
 * attached — never a dead end.
 */
@Component({
  selector: 'app-receipt-confirm-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiBadgeComponent,
    UiButtonComponent,
    UiCardComponent,
    UiCheckboxComponent,
    UiFieldComponent,
    UiInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-2xl px-4 py-6" data-testid="receipt-confirm">
      <ui-page-header titleKey="transactions.scan.confirmTitle" />

      <ui-card>
        @switch (phase()) {
          @case ('loading') {
            <ui-loading testId="confirm-loading" messageKey="transactions.scan.confirmLoading" />
          }
          @case ('processing') {
            <div data-testid="confirm-processing" class="flex flex-col gap-3">
              <ui-alert variant="warning" messageKey="transactions.scan.stillProcessing" />
              <ui-button testId="confirm-manual-entry-button" variant="primary" (click)="switchToManual()">
                {{ 'transactions.scan.proceedManually' | transloco }}
              </ui-button>
            </div>
          }
          @default {
            @if (phase() === 'manual') {
              <ui-alert
                testId="confirm-extraction-failed-alert"
                variant="warning"
                messageKey="transactions.scan.extractionFailedBody"
              />
            }

            <form (ngSubmit)="confirm()" class="flex flex-col gap-3" data-testid="confirm-form">
              <ui-field labelKey="transactions.account">
                <ui-select
                  name="confirmAccountId"
                  [required]="true"
                  testId="confirm-account-select"
                  [options]="accountOptions()"
                  placeholderKey="transactions.selectAccount"
                  [value]="accountId()"
                  (valueChange)="accountId.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.type">
                <ui-select
                  name="confirmType"
                  testId="confirm-type-select"
                  [options]="typeOptions()"
                  [value]="type()"
                  (valueChange)="setType($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.amount">
                @if (isLowConfidence('amount')) {
                  <ui-badge variant="near_limit" testId="confirm-amount-badge">
                    {{ 'transactions.scan.lowConfidence' | transloco }}
                  </ui-badge>
                }
                <ui-input
                  name="confirmAmount"
                  [required]="true"
                  testId="confirm-amount-input"
                  [value]="amount()"
                  (valueChange)="amount.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.date">
                @if (isLowConfidence('occurred_on')) {
                  <ui-badge variant="near_limit" testId="confirm-date-badge">
                    {{ 'transactions.scan.lowConfidence' | transloco }}
                  </ui-badge>
                }
                <ui-input
                  type="date"
                  name="confirmOccurredOn"
                  [required]="true"
                  testId="confirm-date-input"
                  [value]="occurredOn()"
                  (valueChange)="occurredOn.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.notes">
                @if (isLowConfidence('vendor_name')) {
                  <ui-badge variant="near_limit" testId="confirm-notes-badge">
                    {{ 'transactions.scan.lowConfidence' | transloco }}
                  </ui-badge>
                }
                <ui-input
                  name="confirmNotes"
                  testId="confirm-notes-input"
                  [value]="notes()"
                  (valueChange)="notes.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.splits.category">
                <ui-select
                  name="confirmCategoryId"
                  [required]="true"
                  testId="confirm-category-select"
                  [options]="categoryOptions()"
                  placeholderKey="transactions.splits.selectCategory"
                  [value]="categoryId()"
                  (valueChange)="categoryId.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.isRefund" layout="inline">
                <ui-checkbox name="confirmIsRefund" [(checked)]="isRefund" />
              </ui-field>

              <ui-field labelKey="transactions.checked" layout="inline">
                <ui-checkbox name="confirmChecked" [(checked)]="checked" />
              </ui-field>

              <ui-button
                testId="confirm-submit-button"
                type="submit"
                variant="primary"
                [disabled]="!canConfirm()"
              >
                {{ 'transactions.scan.confirmSubmit' | transloco }}
              </ui-button>
            </form>

            @if (errorKey(); as key) {
              <ui-alert testId="confirm-error" [messageKey]="key" />
            }
          }
        }
      </ui-card>
    </section>
  `,
})
export class ReceiptConfirmPage {
  private readonly transactionsService = inject(TransactionsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly handoffService = inject(OcrCaptureHandoffService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );
  protected readonly categoryOptions = computed<UiSelectOption[]>(() =>
    this.categories().map((c) => ({ value: c.id, label: c.name })),
  );
  protected readonly typeOptions = computed<UiSelectOption[]>(() => [
    { value: 'expense', label: 'Expense' },
    { value: 'income', label: 'Income' },
  ]);

  protected readonly phase = signal<ConfirmPhase>('loading');
  protected readonly errorKey = signal<string | null>(null);

  protected readonly accountId = signal('');
  protected readonly type = signal<TransactionType>('expense');
  protected readonly amount = signal('');
  protected readonly occurredOn = signal('');
  protected readonly notes = signal('');
  // Design D134 + this unit's task list: NEVER pre-filled, always
  // required — no auto-categorization from extraction, a hard product
  // constraint, not a suggestion.
  protected readonly categoryId = signal('');
  protected readonly isRefund = signal(false);
  protected readonly checked = signal(false);

  protected readonly canConfirm = computed(
    () => !!this.accountId() && !!this.amount() && !!this.occurredOn() && !!this.categoryId(),
  );

  private transactionId!: string;
  private fieldConfidence: Record<string, number> = {};

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();

    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.phase.set('manual');
      this.errorKey.set('transactions.scan.confirmError');
      return;
    }
    this.transactionId = id;

    // Fast path: Unit 8 already fetched the terminal/timeout outcome in
    // the same session.
    const handoff = this.handoffService.consume();
    if (handoff !== null) {
      this.accountId.set(handoff.accountId);
      this.applyResult(handoff.ocrStatus, handoff.extraction, handoff.timedOut);
      return;
    }

    // `consume()` returned null — no in-memory hand-off available (page
    // refresh, direct navigation, or a lost browser session). This is a
    // REAL, expected case: fall back to an independent fetch instead of
    // assuming a hand-off always exists (design D120's own rationale —
    // drafts are invisible to the plain transaction GET, so this MUST be
    // `getOcrStatus`, never `TransactionsService.getTransaction`).
    this.transactionsService.getOcrStatus(id).subscribe({
      next: (result) => {
        this.accountId.set(result.account_id);
        this.applyResult(result.ocr_status, result.extraction, false);
      },
      error: () => {
        this.phase.set('manual');
        this.errorKey.set('transactions.scan.confirmError');
      },
    });
  }

  private applyResult(
    ocrStatus: OcrStatus,
    extraction: OcrExtraction | null,
    timedOut: boolean,
  ): void {
    if (timedOut || ocrStatus === 'pending_ocr') {
      // Confirm can only ever act on `extracted`/`extraction_failed`
      // (Unit 4's implementation — no skip-OCR escape hatch from
      // `pending_ocr`). Rather than duplicating Unit 8's full 2s/90s poll
      // loop on this rarely-hit edge case (a refresh mid-processing), the
      // user is offered the same graceful "continue manually" path the
      // capture page already establishes for its own timeout.
      this.phase.set('processing');
      return;
    }

    if (ocrStatus === 'extraction_failed' || extraction === null) {
      this.phase.set('manual');
      return;
    }

    this.fieldConfidence = extraction.field_confidence;
    this.amount.set(extraction.amount ?? '');
    this.occurredOn.set(extraction.occurred_on ?? '');
    this.notes.set(extraction.vendor_name ?? '');
    this.phase.set('review');
  }

  protected isLowConfidence(field: string): boolean {
    const confidence = this.fieldConfidence[field];
    return confidence !== undefined && confidence < OCR_LOW_CONFIDENCE_THRESHOLD;
  }

  protected switchToManual(): void {
    this.amount.set('');
    this.occurredOn.set('');
    this.notes.set('');
    this.fieldConfidence = {};
    this.phase.set('manual');
  }

  protected setType(value: string): void {
    this.type.set(value as TransactionType);
  }

  protected confirm(): void {
    this.errorKey.set(null);

    const body: TransactionCreate = {
      account_id: this.accountId(),
      type: this.type(),
      amount: this.amount(),
      occurred_on: this.occurredOn(),
      notes: this.notes() || null,
      is_refund: this.isRefund(),
      checked: this.checked(),
      splits: [{ category_id: this.categoryId(), amount: this.amount() }],
    };

    this.transactionsService.confirmFromPhoto(this.transactionId, body).subscribe({
      next: () => void this.router.navigateByUrl('/transactions'),
      error: (err: HttpErrorResponse) => {
        if (err.status === 409) {
          this.errorKey.set('transactions.scan.confirmConflictError');
          return;
        }
        if (err.status === 422) {
          this.errorKey.set('transactions.validationError');
          return;
        }
        this.errorKey.set('transactions.scan.confirmError');
      },
    });
  }
}
