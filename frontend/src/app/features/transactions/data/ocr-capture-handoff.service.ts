import { Injectable, signal } from '@angular/core';

import { OcrExtraction, OcrStatus } from './transactions.service';

/**
 * The exact hand-off shape from Unit 8 (capture/upload/poll) to Unit 9
 * (confirm/review screen, design D134 — not built yet).
 *
 * `ReceiptCapturePage` never navigates to Unit 9's screen carrying data
 * only in a route param — a draft transaction is invisible to
 * `GET /api/transactions/{id}` by construction (design D120: it is
 * excluded from `visible_transactions`, and is only reachable through
 * `GET /api/transactions/{id}/ocr` or a future confirm call), so Unit 9's
 * page cannot simply re-fetch it the way `TransactionFormPage.loadExisting`
 * fetches an ordinary transaction. Instead this service holds the LAST
 * poll/timeout outcome in memory and `ReceiptCapturePage` navigates to
 * `/transactions/{id}/confirm` (unregistered today — the app's wildcard
 * route redirects it to `''`, design's own `app.routes.ts` `**` rule;
 * Unit 9 registers the real route at that same path). When Unit 9 adds
 * that route, its page reads `consume()` for the terminal outcome this
 * unit already fetched, instead of re-polling from zero.
 *
 * `consume()` clears the held value after reading it, so a page
 * refresh/direct navigation to the confirm URL (no in-memory hand-off)
 * is visibly distinguishable from a real hand-off — Unit 9's page must
 * treat a `null` `consume()` result as "no hand-off available, poll or
 * fetch independently", never assume one always exists.
 */
export interface OcrCaptureHandoff {
  transactionId: string;
  accountId: string;
  ocrStatus: OcrStatus;
  extraction: OcrExtraction | null;
  /** `true` when the 90s poll timeout (design D132) was hit with no
   * terminal `ocr_status` yet — a THIRD case, distinct from
   * `extraction_failed`, per this unit's task: never rendered as an
   * error, always as "proceed to manual entry, the photo is attached". */
  timedOut: boolean;
}

@Injectable({ providedIn: 'root' })
export class OcrCaptureHandoffService {
  private readonly handoff = signal<OcrCaptureHandoff | null>(null);

  set(value: OcrCaptureHandoff): void {
    this.handoff.set(value);
  }

  /** Reads and clears the held hand-off in one step (see class doc). */
  consume(): OcrCaptureHandoff | null {
    const value = this.handoff();
    this.handoff.set(null);
    return value;
  }
}
