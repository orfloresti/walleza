/**
 * `TemplatesService` HTTP contract tests (Phase 4 PR5, task 5.5), same
 * `HttpTestingController` pattern `transfers.service.spec.ts` established
 * — no live backend, only the real `HttpClient` against a mock backend,
 * proving each call hits the exact path/method/body/query-params
 * `app/templates/{router,schemas}.py` defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { TemplatesService } from './templates.service';

const TEMPLATE_RESPONSE = {
  id: 'template-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  name: 'Rent',
  position: 0,
  type: 'expense',
  amount: '1200.00',
  notes: null,
  created_by_user_id: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  splits: [],
};

const TRANSACTION_RESPONSE = {
  id: 'txn-1',
  workspace_id: 'ws-1',
  account_id: 'acc-1',
  type: 'expense',
  amount: '1200.00',
  occurred_on: '2026-01-15',
  notes: null,
  is_refund: false,
  checked: false,
  photo_content_type: null,
  photo_uploaded_at: null,
  created_by_user_id: 'user-1',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z',
  splits: [],
};

describe('TemplatesService', () => {
  let service: TemplatesService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(TemplatesService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/templates lists templates and caches them in the signal', async () => {
    const promise = firstValueFrom(service.listTemplates());

    const req = httpMock.expectOne((r) => r.url === '/api/templates');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.params.keys().length).toBe(0);
    req.flush([TEMPLATE_RESPONSE]);

    const templates = await promise;
    expect(templates).toEqual([TEMPLATE_RESPONSE]);
    expect(service.templates()).toEqual([TEMPLATE_RESPONSE]);
  });

  it('GET /api/templates?account_id sends the filter as a query param when provided', async () => {
    const promise = firstValueFrom(service.listTemplates('acc-1'));

    const req = httpMock.expectOne((r) => r.url === '/api/templates');
    expect(req.request.params.get('account_id')).toBe('acc-1');
    req.flush([]);

    await promise;
  });

  it('POST /api/templates creates a template with the exact body shape, including splits (task focus)', async () => {
    const promise = firstValueFrom(
      service.createTemplate({
        name: 'Rent',
        account_id: 'acc-1',
        type: 'expense',
        amount: '1200.00',
        notes: null,
        position: 0,
        splits: [{ category_id: 'cat-1', amount: '1200.00' }],
      }),
    );

    const req = httpMock.expectOne('/api/templates');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Rent',
      account_id: 'acc-1',
      type: 'expense',
      amount: '1200.00',
      notes: null,
      position: 0,
      splits: [{ category_id: 'cat-1', amount: '1200.00' }],
    });
    expect(typeof req.request.body.amount).toBe('string');
    req.flush(TEMPLATE_RESPONSE);

    const template = await promise;
    expect(template.id).toBe('template-1');
  });

  it('GET /api/templates/{id} fetches a single template', async () => {
    const promise = firstValueFrom(service.getTemplate('template-1'));

    const req = httpMock.expectOne('/api/templates/template-1');
    expect(req.request.method).toBe('GET');
    req.flush(TEMPLATE_RESPONSE);

    const template = await promise;
    expect(template.id).toBe('template-1');
  });

  it('PATCH /api/templates/{id} updates template fields', async () => {
    const promise = firstValueFrom(service.updateTemplate('template-1', { name: 'New rent' }));

    const req = httpMock.expectOne('/api/templates/template-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ name: 'New rent' });
    req.flush({ ...TEMPLATE_RESPONSE, name: 'New rent' });

    const template = await promise;
    expect(template.name).toBe('New rent');
  });

  it('DELETE /api/templates/{id} deletes a template', async () => {
    const promise = firstValueFrom(service.deleteTemplate('template-1'));

    const req = httpMock.expectOne('/api/templates/template-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });

  it('POST /api/templates/{id}/apply with no body override applies against today (defaults server-side, design D56)', async () => {
    const promise = firstValueFrom(service.applyTemplate('template-1'));

    const req = httpMock.expectOne('/api/templates/template-1/apply');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(TRANSACTION_RESPONSE);

    const transaction = await promise;
    expect(transaction.id).toBe('txn-1');
  });

  it('POST /api/templates/{id}/apply sends an explicit occurred_on override when provided (task focus)', async () => {
    const promise = firstValueFrom(
      service.applyTemplate('template-1', { occurred_on: '2026-02-01' }),
    );

    const req = httpMock.expectOne('/api/templates/template-1/apply');
    expect(req.request.body).toEqual({ occurred_on: '2026-02-01' });
    req.flush({ ...TRANSACTION_RESPONSE, occurred_on: '2026-02-01' });

    await promise;
  });
});
