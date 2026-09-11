/**
 * `TemplatesListPage` (Phase 4 PR5, task 5.1): renders `GET /api/templates`
 * and exercises the per-row apply action. Real `HttpClient` against
 * `HttpTestingController`, same pattern as `transfers-list.page.spec.ts`.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { TemplatesListPage } from './templates-list.page';

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

const TEMPLATE = {
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

const TRANSACTION = {
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

const TRANSLATIONS = {
  templates: {
    title: 'Templates',
    loading: 'Loading…',
    loadError: 'Could not load templates.',
    create: 'Add template',
    edit: 'Edit',
    delete: 'Delete',
    deleteError: 'Could not delete that template.',
    apply: 'Apply',
    applyError: 'Could not apply that template.',
  },
};

describe('TemplatesListPage', () => {
  let fixture: ComponentFixture<TemplatesListPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        TemplatesListPage,
        TranslocoTestingModule.forRoot({
          langs: { en: TRANSLATIONS },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(TemplatesListPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushBootstrapRequests(): void {
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT]);
  }

  it('renders the list from GET /api/templates with account name and amount', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();

    const req = httpMock.expectOne((r) => r.url === '/api/templates');
    expect(req.request.method).toBe('GET');
    req.flush([TEMPLATE]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Rent');
    expect(text).toContain('Checking');
    expect(text).toContain('1200.00');
  });

  it('clicking apply calls POST /api/templates/{id}/apply with an empty body when no date override was set (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/templates').flush([TEMPLATE]);
    await fixture.whenStable();
    fixture.detectChanges();

    const applyButton = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="template-apply-template-1"]',
    ) as HTMLButtonElement;
    applyButton.click();

    const req = httpMock.expectOne('/api/templates/template-1/apply');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush(TRANSACTION);
    await fixture.whenStable();
  });

  it('setting a date override before clicking apply sends occurred_on in the request body (task focus)', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/templates').flush([TEMPLATE]);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['setApplyDate']('template-1', '2026-02-01');
    fixture.detectChanges();

    const applyButton = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="template-apply-template-1"]',
    ) as HTMLButtonElement;
    applyButton.click();

    const req = httpMock.expectOne('/api/templates/template-1/apply');
    expect(req.request.body).toEqual({ occurred_on: '2026-02-01' });
    req.flush(TRANSACTION);
    await fixture.whenStable();
  });

  it('clicking delete calls DELETE /api/templates/{id}', async () => {
    fixture.detectChanges();
    flushBootstrapRequests();
    httpMock.expectOne((r) => r.url === '/api/templates').flush([TEMPLATE]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    expect(deleteButton).toBeTruthy();
    deleteButton?.click();

    const req = httpMock.expectOne('/api/templates/template-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    httpMock.expectOne((r) => r.url === '/api/templates').flush([]);
    await fixture.whenStable();
  });
});
