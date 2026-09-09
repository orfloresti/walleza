/**
 * `ReceiptUploadComponent` — Phase 2 PR6b (tasks 8.2/8.3): the 3-step
 * presigned-POST pipeline (design D24/D25). `HttpTestingController`
 * intercepts every `HttpClient` call regardless of origin, so it can
 * assert on the direct-to-S3 POST exactly like the app's own backend
 * calls, even though in production it targets a different origin.
 */
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it } from 'vitest';

import { ReceiptUploadComponent } from './receipt-upload.component';

const UPLOAD_URL_RESPONSE = {
  url: 'https://walleza-receipts-staging.s3.amazonaws.com/',
  // Deliberately in the SAME order boto3's `generate_presigned_post`
  // returns them — the policy/signature fields, THEN Content-Type — to
  // prove the component appends fields in the exact order it receives
  // them, not a re-sorted order of its own choosing.
  fields: {
    key: 'workspaces/ws-1/transactions/txn-1/receipt',
    'x-amz-algorithm': 'AWS4-HMAC-SHA256',
    'x-amz-credential': 'AKIAEXAMPLE/20260101/us-east-1/s3/aws4_request',
    'x-amz-date': '20260101T000000Z',
    policy: 'base64-policy-document',
    'x-amz-signature': 'deadbeef',
    'Content-Type': 'image/jpeg',
  },
  expires_at: '2026-01-01T00:05:00Z',
  max_bytes: 5242880,
  content_type: 'image/jpeg',
};

const CONFIRM_RESPONSE = {
  photo_content_type: 'image/jpeg',
  photo_uploaded_at: '2026-01-01T00:01:00Z',
};

const TRANSLATIONS = {
  transactions: {
    photo: {
      label: 'Receipt photo',
      uploading: 'Uploading…',
      uploadError: 'Could not upload that photo. Please try again.',
    },
  },
};

function createFile(): File {
  return new File(['fake-bytes'], 'receipt.jpg', { type: 'image/jpeg' });
}

function selectFile(fixture: ComponentFixture<ReceiptUploadComponent>, file: File): void {
  const input = (fixture.nativeElement as HTMLElement).querySelector(
    '[data-testid="receipt-file-input"]',
  ) as HTMLInputElement;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  input.dispatchEvent(new Event('change'));
  fixture.detectChanges();
}

async function createFixture(): Promise<ComponentFixture<ReceiptUploadComponent>> {
  await TestBed.configureTestingModule({
    imports: [
      ReceiptUploadComponent,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [provideHttpClient(), provideHttpClientTesting()],
  }).compileComponents();
  return TestBed.createComponent(ReceiptUploadComponent);
}

describe('ReceiptUploadComponent', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('uploadIfSelected completes with no HTTP call at all when no file was selected', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    let completed = false;
    fixture.componentInstance.uploadIfSelected('txn-1').subscribe({
      next: () => (completed = true),
    });

    expect(completed).toBe(true);
  });

  it('runs the 3-step pipeline: upload-url -> direct-to-S3 POST with fields-then-file-last -> confirm only after S3 succeeds (task focus)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    selectFile(fixture, createFile());
    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[data-testid="receipt-selected-file"]')
        ?.textContent,
    ).toContain('receipt.jpg');

    let completed = false;
    fixture.componentInstance.uploadIfSelected('txn-1').subscribe({
      next: () => (completed = true),
    });

    // Step ②
    const uploadUrlReq = httpMock.expectOne('/api/transactions/txn-1/photo/upload-url');
    expect(uploadUrlReq.request.method).toBe('POST');
    expect(uploadUrlReq.request.body).toEqual({ content_type: 'image/jpeg' });
    uploadUrlReq.flush(UPLOAD_URL_RESPONSE);

    // Step ③ — direct-to-S3, a DIFFERENT origin than this app's own
    // `/api/...` calls, still interceptable by HttpTestingController.
    const s3Req = httpMock.expectOne(UPLOAD_URL_RESPONSE.url);
    expect(s3Req.request.method).toBe('POST');
    expect(s3Req.request.withCredentials).toBe(false);

    const formData = s3Req.request.body as FormData;
    const entries = Array.from(formData.entries());
    const expectedFieldKeys = Object.keys(UPLOAD_URL_RESPONSE.fields);
    expect(entries.length).toBe(expectedFieldKeys.length + 1);

    // Every `fields` entry precedes the file field, in the EXACT order
    // the server returned them.
    entries.slice(0, -1).forEach(([key, value], index) => {
      const expectedKey = expectedFieldKeys[index];
      expect(key).toBe(expectedKey);
      expect(value).toBe(
        UPLOAD_URL_RESPONSE.fields[expectedKey as keyof typeof UPLOAD_URL_RESPONSE.fields],
      );
    });

    // The file field is named "file" and is LAST — S3's own documented
    // presigned-POST requirement.
    const [lastKey, lastValue] = entries[entries.length - 1];
    expect(lastKey).toBe('file');
    expect((lastValue as File).name).toBe('receipt.jpg');

    // Confirm (step ④) must not have been requested yet — it may only
    // follow a SUCCESSFUL S3 response.
    httpMock.expectNone('/api/transactions/txn-1/photo');
    expect(completed).toBe(false);

    s3Req.flush(null);

    // Step ④, now that S3 succeeded.
    const confirmReq = httpMock.expectOne('/api/transactions/txn-1/photo');
    expect(confirmReq.request.method).toBe('PUT');
    expect(confirmReq.request.body).toEqual({ content_type: 'image/jpeg' });
    expect(confirmReq.request.withCredentials).toBe(true);
    confirmReq.flush(CONFIRM_RESPONSE);

    expect(completed).toBe(true);
  });

  it('never calls confirm when the direct-to-S3 POST itself fails, and surfaces an upload error', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    selectFile(fixture, createFile());

    let erroredWith: unknown;
    fixture.componentInstance.uploadIfSelected('txn-1').subscribe({
      error: (err: unknown) => (erroredWith = err),
    });

    const uploadUrlReq = httpMock.expectOne('/api/transactions/txn-1/photo/upload-url');
    uploadUrlReq.flush(UPLOAD_URL_RESPONSE);

    const s3Req = httpMock.expectOne(UPLOAD_URL_RESPONSE.url);
    s3Req.flush('access denied', { status: 403, statusText: 'Forbidden' });

    httpMock.expectNone('/api/transactions/txn-1/photo');
    expect(erroredWith).toBeDefined();
    fixture.detectChanges();
    expect(
      (fixture.nativeElement as HTMLElement).querySelector(
        '[data-testid="receipt-upload-error"]',
      )?.textContent,
    ).toContain('Could not upload that photo');
  });
});
