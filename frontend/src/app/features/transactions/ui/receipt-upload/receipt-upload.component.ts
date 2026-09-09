import { HttpClient } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { Observable, of, switchMap, throwError } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { TransactionsService } from '../../data/transactions.service';

/**
 * Receipt-photo picker + the 3-step upload pipeline (Phase 2 PR6b, task
 * 8.2, design D24/D25):
 *
 *   ② `TransactionsService.requestPhotoUploadUrl` — the presigned
 *      `generate_presigned_post` payload (`url` + `fields`), only
 *      obtainable once a transaction id already exists (step ① — the
 *      parent form's own create/update call, run BEFORE this component's
 *      `uploadIfSelected` is ever invoked; photo-first is impossible by
 *      construction, exactly as D24 intends).
 *   ③ a `FormData` built from every one of those `fields` entries, in
 *      the exact order the server returned them, THEN the file itself
 *      appended last under the key `"file"` — S3's own documented
 *      presigned-POST requirement — POSTed DIRECTLY to the returned
 *      `url` (a different origin; never through this app's own backend,
 *      never `withCredentials`, since the presigned policy itself is the
 *      authorization, not a session cookie).
 *   ④ `TransactionsService.confirmPhotoUpload` — only once step ③'s
 *      direct-to-S3 POST has itself resolved successfully.
 *
 * This component owns no transaction id itself and makes no HTTP call
 * unless a file was actually selected — `uploadIfSelected(transactionId)`
 * is the parent form's (`TransactionFormPage`) hand-off point, called
 * only after its own save() resolves.
 */
@Component({
  selector: 'app-receipt-upload',
  imports: [TranslocoPipe],
  template: `
    <div data-testid="receipt-upload">
      <label>
        {{ 'transactions.photo.label' | transloco }}
        <input
          type="file"
          data-testid="receipt-file-input"
          accept="image/jpeg,image/png,image/webp,image/heic"
          (change)="onFileSelected($event)"
        />
      </label>

      @if (selectedFile(); as file) {
        <p data-testid="receipt-selected-file">{{ file.name }}</p>
      }

      @if (uploading()) {
        <p data-testid="receipt-uploading">{{ 'transactions.photo.uploading' | transloco }}</p>
      }

      @if (errorKey(); as key) {
        <p role="alert" data-testid="receipt-upload-error">{{ key | transloco }}</p>
      }
    </div>
  `,
})
export class ReceiptUploadComponent {
  private readonly transactionsService = inject(TransactionsService);
  private readonly http = inject(HttpClient);

  protected readonly selectedFile = signal<File | null>(null);
  protected readonly uploading = signal(false);
  protected readonly errorKey = signal<string | null>(null);

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile.set(input.files?.[0] ?? null);
    this.errorKey.set(null);
  }

  /**
   * Runs design D24's steps ②③④ against `transactionId` when a file is
   * selected; completes immediately with no HTTP call at all when it is
   * not (splits-only saves, or the basic no-photo case PR6 already
   * covers, must never trigger a spurious upload attempt).
   */
  uploadIfSelected(transactionId: string): Observable<void> {
    const file = this.selectedFile();
    if (!file) {
      return of(undefined);
    }

    this.uploading.set(true);
    this.errorKey.set(null);
    const contentType = file.type;

    return this.transactionsService.requestPhotoUploadUrl(transactionId, contentType).pipe(
      switchMap((uploadUrl) => {
        // Every presigned-POST policy field precedes the actual file
        // field, which is named "file" and MUST be appended last — this
        // order is load-bearing (S3 rejects a POST where "file" is not
        // the final field), not stylistic.
        const formData = new FormData();
        for (const [key, value] of Object.entries(uploadUrl.fields)) {
          formData.append(key, value);
        }
        formData.append('file', file);

        // Direct browser-to-S3 request — never through this app's own
        // backend (that is the entire point of a presigned POST) and
        // never `withCredentials`: a different origin, and the signed
        // policy itself is the authorization, not a cookie.
        return this.http.post(uploadUrl.url, formData).pipe(
          switchMap(() =>
            this.transactionsService.confirmPhotoUpload(transactionId, contentType),
          ),
        );
      }),
      map(() => {
        this.uploading.set(false);
      }),
      catchError((error: unknown) => {
        this.uploading.set(false);
        this.errorKey.set('transactions.photo.uploadError');
        return throwError(() => error);
      }),
    );
  }
}
