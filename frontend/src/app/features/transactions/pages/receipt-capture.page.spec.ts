/**
 * `ReceiptCapturePage` — Phase 9, Unit 8 (design D131/D132/D133): the
 * entry point renders, the draft-creation + direct-to-S3 upload pipeline,
 * the 2s-interval poll loop stopping on a terminal `ocr_status`, and the
 * 90s-timeout graceful degrade to manual entry. Real `HttpClient` against
 * `HttpTestingController`, fake timers for the rxjs `interval`/`timer`
 * poll loop (design D132's exact `core/app-update.service.ts`-style
 * shape).
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { OcrCaptureHandoffService } from '../data/ocr-capture-handoff.service';
import { ReceiptCapturePage } from './receipt-capture.page';

const ACCOUNT = {
  id: 'acc-1',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Checking',
  currency: 'USD',
  exchange_rate: '1',
  initial_funds: '100.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const DRAFT_RESPONSE = {
  transaction_id: 'txn-draft-1',
  url: 'https://walleza-receipts-staging.s3.amazonaws.com/',
  fields: { key: 'workspaces/ws-1/transactions/txn-draft-1/receipt' },
  expires_at: '2026-01-01T00:05:00Z',
  max_bytes: 5242880,
  content_type: 'image/jpeg',
};

const TRANSLATIONS = {
  transactions: {
    account: 'Account',
    selectAccount: 'Select an account',
    photo: { label: 'Receipt photo' },
    scan: {
      entry: 'Scan receipt',
      pageTitle: 'Scan a receipt',
      submit: 'Scan',
      uploading: 'Uploading your receipt…',
      polling: 'Reading your receipt…',
      timeoutBody: "We couldn't finish reading your receipt in time.",
      proceedManually: 'Continue manually',
      draftError: 'Could not start scanning that receipt.',
      uploadError: 'Could not upload that photo.',
      pollError: 'Something went wrong while reading your receipt.',
    },
  },
};

function createFile(): File {
  return new File(['fake-bytes'], 'receipt.jpg', { type: 'image/jpeg' });
}

function selectAccount(fixture: ComponentFixture<ReceiptCapturePage>, accountId: string): void {
  const select = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="scan-account-select"]',
  ) as HTMLSelectElement;
  select.value = accountId;
  select.dispatchEvent(new Event('change'));
  fixture.detectChanges();
}

function selectFile(fixture: ComponentFixture<ReceiptCapturePage>, file: File): void {
  const input = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="scan-file-input"]',
  ) as HTMLInputElement;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  input.dispatchEvent(new Event('change'));
  fixture.detectChanges();
}

function submit(fixture: ComponentFixture<ReceiptCapturePage>): void {
  const form = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="scan-form"]',
  ) as HTMLFormElement;
  form.dispatchEvent(new Event('submit'));
  fixture.detectChanges();
}

async function createFixture(): Promise<ComponentFixture<ReceiptCapturePage>> {
  await TestBed.configureTestingModule({
    imports: [
      ReceiptCapturePage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [provideHttpClient(), provideHttpClientTesting()],
  }).compileComponents();
  return TestBed.createComponent(ReceiptCapturePage);
}

describe('ReceiptCapturePage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
    vi.useRealTimers();
  });

  it('renders the entry form and lists accounts', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="receipt-capture"]'),
    ).toBeTruthy();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="scan-form"]'),
    ).toBeTruthy();
  });

  it('runs draft-from-photo -> direct-to-S3 upload once account + file are selected (task focus)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    fixture.detectChanges();

    selectAccount(fixture, 'acc-1');
    selectFile(fixture, createFile());
    submit(fixture);

    const draftReq = httpMock.expectOne('/api/transactions/draft-from-photo');
    expect(draftReq.request.method).toBe('POST');
    expect(draftReq.request.body).toEqual({ account_id: 'acc-1', content_type: 'image/jpeg' });
    draftReq.flush(DRAFT_RESPONSE);

    const s3Req = httpMock.expectOne(DRAFT_RESPONSE.url);
    expect(s3Req.request.method).toBe('POST');
    expect(s3Req.request.withCredentials).toBe(false);
    s3Req.flush(null);

    fixture.detectChanges();
    // Upload succeeded -> the page must now be polling, not idle/erroring;
    // the actual 2s-interval poll request is covered by the fake-timer
    // tests below.
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="scan-polling"]'),
    ).toBeTruthy();
    httpMock.expectNone('/api/transactions/txn-draft-1/ocr');
  });

  it('polls every 2s and stops as soon as a terminal ocr_status arrives, then navigates to the confirm hand-off route', async () => {
    vi.useFakeTimers();
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    const router = TestBed.inject(Router);
    const handoffService = TestBed.inject(OcrCaptureHandoffService);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    const handoffSpy = vi.spyOn(handoffService, 'set');

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    fixture.detectChanges();

    selectAccount(fixture, 'acc-1');
    selectFile(fixture, createFile());
    submit(fixture);

    httpMock.expectOne('/api/transactions/draft-from-photo').flush(DRAFT_RESPONSE);
    httpMock.expectOne(DRAFT_RESPONSE.url).flush(null);

    // First poll, 2s after the upload resolved — still pending.
    await vi.advanceTimersByTimeAsync(2000);
    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'pending_ocr', extraction: null });

    // Second poll — terminal. No THIRD poll should ever be issued.
    await vi.advanceTimersByTimeAsync(2000);
    const extraction = {
      status: 'succeeded',
      failure_reason: null,
      amount: '12.34',
      occurred_on: '2026-01-15',
      vendor_name: 'Coffee Shop',
      currency: 'USD',
      field_confidence: {},
    };
    httpMock
      .expectOne('/api/transactions/txn-draft-1/ocr')
      .flush({ ocr_status: 'extracted', extraction });

    httpMock.expectNone('/api/transactions/txn-draft-1/ocr');
    expect(handoffSpy).toHaveBeenCalledWith({
      transactionId: 'txn-draft-1',
      accountId: 'acc-1',
      ocrStatus: 'extracted',
      extraction,
      timedOut: false,
    });
    expect(navigateSpy).toHaveBeenCalledWith('/transactions/txn-draft-1/confirm');
  });

  it('degrades gracefully at the 90s timeout: stops polling, shows no error, offers manual entry (task focus)', async () => {
    vi.useFakeTimers();
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    const handoffService = TestBed.inject(OcrCaptureHandoffService);
    const handoffSpy = vi.spyOn(handoffService, 'set');

    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    fixture.detectChanges();

    selectAccount(fixture, 'acc-1');
    selectFile(fixture, createFile());
    submit(fixture);

    httpMock.expectOne('/api/transactions/draft-from-photo').flush(DRAFT_RESPONSE);
    httpMock.expectOne(DRAFT_RESPONSE.url).flush(null);

    // 45 polls fit inside 90s (2000ms * 45 = 90000ms); flush every poll
    // as still-pending so the loop only ever ends via the 90s timeout,
    // never via a terminal status.
    for (let i = 0; i < 44; i++) {
      await vi.advanceTimersByTimeAsync(2000);
      httpMock
        .expectOne('/api/transactions/txn-draft-1/ocr')
        .flush({ ocr_status: 'pending_ocr', extraction: null });
    }

    // Advancing past the 90s mark completes the poll stream via
    // `takeUntil(timer(90_000))` regardless of any in-flight request.
    await vi.advanceTimersByTimeAsync(2000);
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="scan-timeout"]'),
    ).toBeTruthy();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="scan-error"]'),
    ).toBeFalsy();
    expect(handoffSpy).toHaveBeenCalledWith({
      transactionId: 'txn-draft-1',
      accountId: 'acc-1',
      ocrStatus: 'pending_ocr',
      extraction: null,
      timedOut: true,
    });

    // No poll fires after the timeout.
    httpMock.expectNone('/api/transactions/txn-draft-1/ocr');
  });

  it('surfaces a 429 as a rate-limit message, never as the generic draft error', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
    fixture.detectChanges();

    selectAccount(fixture, 'acc-1');
    selectFile(fixture, createFile());
    submit(fixture);

    httpMock.expectOne('/api/transactions/draft-from-photo').flush(
      {
        detail: 'daily photo-capture limit reached',
        limit: 20,
        used: 20,
        resets_at: '2026-01-16T00:00:00Z',
      },
      { status: 429, statusText: 'Too Many Requests' },
    );
    fixture.detectChanges();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="scan-rate-limited"]')
        ?.textContent,
    ).toContain('2026-01-16T00:00:00Z');
  });
});
