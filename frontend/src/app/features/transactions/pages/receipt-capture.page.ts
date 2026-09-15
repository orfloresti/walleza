import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { Subscription, interval, switchMap, takeUntil, takeWhile, timer } from 'rxjs';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiFieldComponent,
  UiFileInputComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { OcrCaptureHandoffService } from '../data/ocr-capture-handoff.service';
import { OcrExtraction, OcrStatus, TransactionsService } from '../data/transactions.service';

/** Design D132: poll every 2s, hard-timeout at 90s (45 polls) — the same
 * `interval`-based rxjs shape `core/app-update.service.ts` established as
 * this app's only prior polling precedent. */
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 90_000;

type CapturePhase = 'idle' | 'uploading' | 'polling' | 'timeout' | 'rateLimited' | 'error';

/**
 * "Scan receipt" entry point (design D133): pick an account and a photo,
 * `draft-from-photo` -> direct-to-S3 upload -> poll `GET
 * /api/transactions/{id}/ocr` until a terminal `ocr_status` or the 90s
 * timeout (design D132). See `OcrCaptureHandoffService`'s doc comment for
 * the exact Unit-9 hand-off shape this page produces at every one of its
 * exits (`extracted`, `extraction_failed`, and the timeout's graceful
 * degrade-to-manual-entry path).
 */
@Component({
  selector: 'app-receipt-capture-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiFieldComponent,
    UiFileInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-2xl px-4 py-6" data-testid="receipt-capture">
      <ui-page-header titleKey="transactions.scan.pageTitle" />

      <ui-card>
        @switch (phase()) {
          @case ('uploading') {
            <ui-loading testId="scan-uploading" messageKey="transactions.scan.uploading" />
          }
          @case ('polling') {
            <ui-loading testId="scan-polling" messageKey="transactions.scan.polling" />
          }
          @case ('timeout') {
            <div data-testid="scan-timeout" class="flex flex-col gap-3">
              <ui-alert variant="warning" messageKey="transactions.scan.timeoutBody" />
              <ui-button testId="scan-manual-entry-button" variant="primary" (click)="proceedToManualEntry()">
                {{ 'transactions.scan.proceedManually' | transloco }}
              </ui-button>
            </div>
          }
          @case ('rateLimited') {
            <ui-alert
              testId="scan-rate-limited"
              variant="warning"
              [message]="rateLimitMessage()"
            />
          }
          @default {
            <form (ngSubmit)="scan()" class="flex flex-col gap-3" data-testid="scan-form">
              <ui-field labelKey="transactions.account">
                <ui-select
                  name="scanAccountId"
                  [required]="true"
                  testId="scan-account-select"
                  [options]="accountOptions()"
                  placeholderKey="transactions.selectAccount"
                  [value]="accountId()"
                  (valueChange)="accountId.set($event)"
                />
              </ui-field>

              <ui-field labelKey="transactions.photo.label">
                <ui-file-input
                  testId="scan-file-input"
                  accept="image/*"
                  capture="environment"
                  (fileSelected)="onFileSelected($event)"
                />
              </ui-field>

              @if (selectedFile(); as file) {
                <p data-testid="scan-selected-file">{{ file.name }}</p>
              }

              <ui-button testId="scan-button" type="submit" variant="primary" [disabled]="!canScan()">
                {{ 'transactions.scan.submit' | transloco }}
              </ui-button>
            </form>

            @if (errorKey(); as key) {
              <ui-alert testId="scan-error" [messageKey]="key" />
            }
          }
        }
      </ui-card>
    </section>
  `,
})
export class ReceiptCapturePage implements OnDestroy {
  private readonly transactionsService = inject(TransactionsService);
  private readonly accountsService = inject(AccountsService);
  private readonly handoffService = inject(OcrCaptureHandoffService);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  protected readonly accountId = signal('');
  protected readonly selectedFile = signal<File | null>(null);
  protected readonly phase = signal<CapturePhase>('idle');
  protected readonly errorKey = signal<string | null>(null);
  protected readonly rateLimitMessage = signal<string | null>(null);

  protected readonly canScan = computed(() => !!this.accountId() && !!this.selectedFile());

  /** Set once `draft-from-photo` resolves; the manual-entry fallback and
   * the poll loop both need it after that point. */
  private draftTransactionId: string | null = null;
  private pollSubscription: Subscription | null = null;
  /** Guards against the poll stream's `complete` firing AFTER a terminal
   * `ocr_status` was already handled by `next` — `takeWhile(..., true)`
   * completing naturally on its own inclusive emission and
   * `takeUntil(timer(...))` completing on timeout both route through the
   * same `complete` callback, and only one of those two causes is ever
   * the timeout. */
  private settled = false;

  constructor() {
    this.accountsService.listAccounts().subscribe();
  }

  protected onFileSelected(file: File | null): void {
    this.selectedFile.set(file);
    this.errorKey.set(null);
  }

  protected scan(): void {
    const file = this.selectedFile();
    const accountId = this.accountId();
    if (!file || !accountId) {
      return;
    }

    this.errorKey.set(null);
    this.phase.set('uploading');
    const contentType = file.type;

    this.transactionsService.createPhotoDraft(accountId, contentType).subscribe({
      next: (draft) => {
        this.draftTransactionId = draft.transaction_id;
        this.transactionsService.uploadToPresignedUrl(draft, file).subscribe({
          next: () => this.startPolling(draft.transaction_id, accountId),
          error: () => {
            this.phase.set('error');
            this.errorKey.set('transactions.scan.uploadError');
          },
        });
      },
      error: (err: HttpErrorResponse) => {
        if (err.status === 429) {
          this.phase.set('rateLimited');
          const detail = err.error as { resets_at?: string } | null;
          this.rateLimitMessage.set(
            detail?.resets_at
              ? `Daily receipt-scan limit reached. Try again after ${detail.resets_at}.`
              : 'Daily receipt-scan limit reached. Please try again tomorrow.',
          );
          return;
        }
        this.phase.set('error');
        this.errorKey.set('transactions.scan.draftError');
      },
    });
  }

  private startPolling(transactionId: string, accountId: string): void {
    this.phase.set('polling');
    this.settled = false;
    const isPending = (status: OcrStatus) => status === 'pending_ocr';

    this.pollSubscription = interval(POLL_INTERVAL_MS)
      .pipe(
        switchMap(() => this.transactionsService.getOcrStatus(transactionId)),
        takeWhile((result) => isPending(result.ocr_status), true),
        takeUntil(timer(POLL_TIMEOUT_MS)),
      )
      .subscribe({
        next: (result) => {
          if (!isPending(result.ocr_status)) {
            this.settled = true;
            this.onTerminal(transactionId, accountId, result.ocr_status, result.extraction);
          }
        },
        error: () => {
          this.settled = true;
          this.phase.set('error');
          this.errorKey.set('transactions.scan.pollError');
        },
        complete: () => {
          if (!this.settled) {
            this.settled = true;
            this.onTimeout(transactionId, accountId);
          }
        },
      });
  }

  private onTerminal(
    transactionId: string,
    accountId: string,
    ocrStatus: OcrStatus,
    extraction: OcrExtraction | null,
  ): void {
    this.pollSubscription?.unsubscribe();
    this.handoffService.set({ transactionId, accountId, ocrStatus, extraction, timedOut: false });
    void this.router.navigateByUrl(`/transactions/${transactionId}/confirm`);
  }

  /** Design D132's graceful degrade: no error is shown, the draft and its
   * photo are already saved server-side, and the user is offered a way
   * forward rather than left stuck on a spinner. */
  private onTimeout(transactionId: string, accountId: string): void {
    this.phase.set('timeout');
    this.handoffService.set({
      transactionId,
      accountId,
      ocrStatus: 'pending_ocr',
      extraction: null,
      timedOut: true,
    });
  }

  protected proceedToManualEntry(): void {
    const id = this.draftTransactionId;
    if (!id) {
      return;
    }
    void this.router.navigateByUrl(`/transactions/${id}/confirm`);
  }

  ngOnDestroy(): void {
    this.pollSubscription?.unsubscribe();
  }
}
