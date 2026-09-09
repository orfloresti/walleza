/**
 * `TransferFormPage` (Phase 3 PR2, task 2.4): create-only form — two
 * account selects (from/to), amount, date, notes. Real `HttpClient`
 * against `HttpTestingController`, same pattern as
 * `transaction-form.page.spec.ts`. There is no `:id` route param
 * handling to test here (design D43: no edit mode exists at all).
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

import { TransferFormPage } from './transfer-form.page';

const ACCOUNT_A = {
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

const ACCOUNT_B = {
  id: 'acc-2',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Savings',
  currency: 'USD',
  exchange_rate: '1',
  initial_funds: '0.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const TRANSFER = {
  id: 'transfer-1',
  workspace_id: 'ws-1',
  from_account_id: 'acc-1',
  to_account_id: 'acc-2',
  from_amount: '100.00',
  to_amount: '50.00',
  occurred_on: '2026-01-15',
  notes: 'Moving savings',
  created_by_user_id: 'user-1',
  created_at: '2026-01-15T00:00:00Z',
  updated_at: '2026-01-15T00:00:00Z',
};

const TRANSLATIONS = {
  transfers: {
    createTitle: 'Add transfer',
    loading: 'Loading…',
    fromAccount: 'From account',
    toAccount: 'To account',
    selectAccount: 'Select an account',
    amount: 'Amount',
    date: 'Date',
    notes: 'Notes',
    create: 'Add transfer',
    saveError: 'Could not create that transfer.',
  },
};

async function createFixture(): Promise<ComponentFixture<TransferFormPage>> {
  await TestBed.configureTestingModule({
    imports: [
      TransferFormPage,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [provideHttpClient(), provideHttpClientTesting()],
  }).compileComponents();

  return TestBed.createComponent(TransferFormPage);
}

/** Flushes the one read-only lookup this page fires from its
 * constructor (`AccountsService.listAccounts`) to populate BOTH account
 * dropdowns from the same list. */
function flushAccounts(httpMock: HttpTestingController): void {
  httpMock.expectOne((r) => r.url === '/api/accounts').flush([ACCOUNT_A, ACCOUNT_B]);
}

describe('TransferFormPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('populates both the from and to account selects from the SAME accounts service call (task focus)', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushAccounts(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const fromOptions = Array.from(
      el.querySelectorAll('[data-testid="transfer-from-account-select"] option'),
    ).map((o) => o.textContent);
    const toOptions = Array.from(
      el.querySelectorAll('[data-testid="transfer-to-account-select"] option'),
    ).map((o) => o.textContent);

    expect(fromOptions).toContain('Checking');
    expect(fromOptions).toContain('Savings');
    expect(toOptions).toContain('Checking');
    expect(toOptions).toContain('Savings');
  });

  it('submitting the form calls POST /api/transfers with the exact body shape and NEVER sends to_amount (task focus)', async () => {
    const fixture = await createFixture();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushAccounts(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['fromAccountId'].set('acc-1');
    component['toAccountId'].set('acc-2');
    component['amount'].set('100.00');
    component['occurredOn'].set('2026-01-15');
    component['notes'].set('Moving savings');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transfers');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      from_account_id: 'acc-1',
      to_account_id: 'acc-2',
      from_amount: '100.00',
      occurred_on: '2026-01-15',
      notes: 'Moving savings',
    });
    expect(typeof req.request.body.from_amount).toBe('string');
    // Confirm to_amount is genuinely absent from the request body — the
    // form computes no client-side conversion preview and never sends a
    // destination amount (design D40/D44).
    expect('to_amount' in req.request.body).toBe(false);
    req.flush(TRANSFER);
    await fixture.whenStable();

    expect(navigateSpy).toHaveBeenCalledWith('/transfers');
  });

  it('renders the server 422 detail verbatim on save failure, without navigating away (task focus)', async () => {
    const fixture = await createFixture();
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushAccounts(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['fromAccountId'].set('acc-1');
    component['toAccountId'].set('acc-1');
    component['amount'].set('100.00');
    component['occurredOn'].set('2026-01-15');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/transfers');
    req.flush(
      { detail: 'from_account_id and to_account_id must be different accounts' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="transfer-server-error"]')?.textContent).toContain(
      'from_account_id and to_account_id must be different accounts',
    );
  });

  it('has no edit-mode/update code path — the page never issues a PATCH', async () => {
    const fixture = await createFixture();
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    flushAccounts(httpMock);
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.componentInstance).not.toHaveProperty('isEditMode');
    expect(fixture.componentInstance).not.toHaveProperty('transferId');
  });
});
