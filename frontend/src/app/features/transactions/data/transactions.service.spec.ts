/**
 * `TransactionsService` HTTP contract tests (Phase 2 PR6, task 7.5), same
 * `HttpTestingController` pattern `accounts.service.spec.ts` established
 * in Phase 1 — no live backend, only the real `HttpClient` against a mock
 * backend, proving each call hits the exact path/method/body/query-params
 * `app/transactions/{router,schemas}.py` defines. Only the BASIC-case
 * (no splits, no photo) surface is exercised here — PR6b covers the
 * split/photo additions.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { TransactionsService } from './transactions.service';

const TRANSACTION_RESPONSE = {
  id: 'txn-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  type: 'expense',
  amount: '42.50',
  occurred_on: '2026-01-15',
  notes: 'Groceries',
  is_refund: false,
  checked: false,
  photo_content_type: null,
  photo_uploaded_at: null,
  created_by_user_id: 'user-1',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z',
  splits: [],
};

describe('TransactionsService', () => {
  let service: TransactionsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TransactionsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/transactions with no filters lists the workspace-wide feed and caches it', async () => {
    const promise = firstValueFrom(service.listTransactions());

    const req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.params.keys().length).toBe(0);
    req.flush([TRANSACTION_RESPONSE]);

    const transactions = await promise;
    expect(transactions).toEqual([TRANSACTION_RESPONSE]);
    expect(service.transactions()).toEqual([TRANSACTION_RESPONSE]);
  });

  it('GET /api/transactions sends every provided filter as a query param (task focus)', async () => {
    const promise = firstValueFrom(
      service.listTransactions({
        account_id: 'acc-1',
        category_id: 'cat-1',
        date_from: '2026-01-01',
        date_to: '2026-01-31',
        type: 'expense',
      }),
    );

    const req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    expect(req.request.params.get('category_id')).toBe('cat-1');
    expect(req.request.params.get('date_from')).toBe('2026-01-01');
    expect(req.request.params.get('date_to')).toBe('2026-01-31');
    expect(req.request.params.get('type')).toBe('expense');
    req.flush([]);

    await promise;
  });

  it('GET /api/transactions omits filters that are not provided', async () => {
    const promise = firstValueFrom(service.listTransactions({ account_id: 'acc-1' }));

    const req = httpMock.expectOne((r) => r.url === '/api/transactions');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    expect(req.request.params.has('category_id')).toBe(false);
    expect(req.request.params.has('date_from')).toBe(false);
    expect(req.request.params.has('date_to')).toBe(false);
    expect(req.request.params.has('type')).toBe(false);
    req.flush([]);

    await promise;
  });

  it('POST /api/transactions creates a transaction with the exact BASIC-case body shape, money as a string (task focus)', async () => {
    const promise = firstValueFrom(
      service.createTransaction({
        account_id: 'acc-1',
        type: 'expense',
        amount: '42.50',
        occurred_on: '2026-01-15',
        notes: 'Groceries',
        is_refund: false,
        checked: false,
      }),
    );

    const req = httpMock.expectOne('/api/transactions');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      account_id: 'acc-1',
      type: 'expense',
      amount: '42.50',
      occurred_on: '2026-01-15',
      notes: 'Groceries',
      is_refund: false,
      checked: false,
    });
    // Money travels as a string on the wire (design D19) — never silently
    // coerced to a JS number anywhere in this round trip.
    expect(typeof req.request.body.amount).toBe('string');
    expect(req.request.body.splits).toBeUndefined();
    req.flush(TRANSACTION_RESPONSE);

    const transaction = await promise;
    expect(transaction.amount).toBe('42.50');
  });

  it('GET /api/transactions/{id} fetches a single transaction', async () => {
    const promise = firstValueFrom(service.getTransaction('txn-1'));

    const req = httpMock.expectOne('/api/transactions/txn-1');
    expect(req.request.method).toBe('GET');
    req.flush(TRANSACTION_RESPONSE);

    const transaction = await promise;
    expect(transaction.id).toBe('txn-1');
  });

  it('PATCH /api/transactions/{id} updates transaction fields without ever sending splits (task focus)', async () => {
    const promise = firstValueFrom(
      service.updateTransaction('txn-1', { amount: '50.00', checked: true }),
    );

    const req = httpMock.expectOne('/api/transactions/txn-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ amount: '50.00', checked: true });
    expect(req.request.body.splits).toBeUndefined();
    req.flush({ ...TRANSACTION_RESPONSE, amount: '50.00', checked: true });

    const transaction = await promise;
    expect(transaction.amount).toBe('50.00');
    expect(transaction.checked).toBe(true);
  });

  it('DELETE /api/transactions/{id} deletes a transaction', async () => {
    const promise = firstValueFrom(service.deleteTransaction('txn-1'));

    const req = httpMock.expectOne('/api/transactions/txn-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });

  it('POST /api/transactions sends an inline splits array when provided (PR6b, task focus)', async () => {
    const promise = firstValueFrom(
      service.createTransaction({
        account_id: 'acc-1',
        type: 'expense',
        amount: '100.00',
        occurred_on: '2026-01-15',
        splits: [
          { category_id: 'cat-1', amount: '60.00' },
          { category_id: 'cat-2', amount: '40.00' },
        ],
      }),
    );

    const req = httpMock.expectOne('/api/transactions');
    expect(req.request.body.splits).toEqual([
      { category_id: 'cat-1', amount: '60.00' },
      { category_id: 'cat-2', amount: '40.00' },
    ]);
    req.flush({ ...TRANSACTION_RESPONSE, amount: '100.00' });

    await promise;
  });

  it('POST /api/transactions/{id}/photo/upload-url requests a presigned upload URL (PR6b, task focus)', async () => {
    const uploadUrlResponse = {
      url: 'https://walleza-receipts-staging.s3.amazonaws.com/',
      fields: { key: 'workspaces/ws-1/transactions/txn-1/receipt', 'Content-Type': 'image/jpeg' },
      expires_at: '2026-01-01T00:05:00Z',
      max_bytes: 5242880,
      content_type: 'image/jpeg',
    };
    const promise = firstValueFrom(service.requestPhotoUploadUrl('txn-1', 'image/jpeg'));

    const req = httpMock.expectOne('/api/transactions/txn-1/photo/upload-url');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ content_type: 'image/jpeg' });
    expect(req.request.withCredentials).toBe(true);
    req.flush(uploadUrlResponse);

    const result = await promise;
    expect(result).toEqual(uploadUrlResponse);
  });

  it('PUT /api/transactions/{id}/photo confirms an uploaded photo (PR6b, task focus)', async () => {
    const confirmResponse = {
      photo_content_type: 'image/jpeg',
      photo_uploaded_at: '2026-01-01T00:01:00Z',
    };
    const promise = firstValueFrom(service.confirmPhotoUpload('txn-1', 'image/jpeg'));

    const req = httpMock.expectOne('/api/transactions/txn-1/photo');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ content_type: 'image/jpeg' });
    req.flush(confirmResponse);

    const result = await promise;
    expect(result).toEqual(confirmResponse);
  });

  it('GET /api/transactions/{id}/photo requests a presigned download URL (PR6b, task focus)', async () => {
    const downloadResponse = { url: 'https://example-bucket.s3.amazonaws.com/signed', expires_at: '2026-01-01T00:05:00Z' };
    const promise = firstValueFrom(service.getPhotoDownloadUrl('txn-1'));

    const req = httpMock.expectOne('/api/transactions/txn-1/photo');
    expect(req.request.method).toBe('GET');
    req.flush(downloadResponse);

    const result = await promise;
    expect(result).toEqual(downloadResponse);
  });
});
