/**
 * `AccountsListPage` — Phase 1 PR4b (tasks 8.1/8.2/8.4): renders
 * `GET /api/accounts`, toggles between active/archived, creates an
 * account, and archives one via `PATCH { archived: true }`. Real
 * `HttpClient` against `HttpTestingController`, no live backend — same
 * pattern as `workspace.page.spec.ts`.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AccountsListPage } from './accounts-list.page';

const SHARED_ACCOUNT = {
  id: 'acc-1',
  workspace_id: 'ws-1',
  owner_user_id: null,
  name: 'Checking',
  currency: 'USD',
  exchange_rate: '1.00000000',
  initial_funds: '100.00',
  is_personal: false,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const PERSONAL_ACCOUNT = {
  ...SHARED_ACCOUNT,
  id: 'acc-2',
  owner_user_id: 'user-1',
  name: 'My Wallet',
  is_personal: true,
};

const ARCHIVED_ACCOUNT = {
  ...SHARED_ACCOUNT,
  id: 'acc-3',
  name: 'Old Account',
  archived: true,
};

describe('AccountsListPage', () => {
  let fixture: ComponentFixture<AccountsListPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        AccountsListPage,
        TranslocoTestingModule.forRoot({
          langs: {
            en: {
              accounts: {
                title: 'Accounts',
                loading: 'Loading…',
                loadError: 'Could not load your accounts.',
                showArchived: 'Show archived',
                personalBadge: 'Personal',
                archivedBadge: 'Archived',
                archive: 'Archive',
                archiveError: 'Could not archive that account.',
                createTitle: 'Add account',
                name: 'Name',
                currency: 'Currency',
                exchangeRate: 'Exchange rate',
                initialFunds: 'Initial funds',
                isPersonal: 'Personal account',
                create: 'Create',
                createError: 'Could not create that account.',
              },
            },
          },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AccountsListPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('lists active accounts by default, excluding archived ones', async () => {
    fixture.detectChanges();

    const req = httpMock.expectOne((r) => r.url === '/api/accounts');
    expect(req.request.params.get('archived')).toBe('false');
    req.flush([SHARED_ACCOUNT, PERSONAL_ACCOUNT]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Checking');
    expect(text).toContain('My Wallet');
    expect(text).not.toContain('Old Account');
  });

  it('marks a personal account with a visible badge, distinguishing it from shared accounts', async () => {
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([SHARED_ACCOUNT, PERSONAL_ACCOUNT]);
    await fixture.whenStable();
    fixture.detectChanges();

    const badges = (fixture.nativeElement as HTMLElement).querySelectorAll(
      '[data-testid="personal-badge"]',
    );
    expect(badges.length).toBe(1);
  });

  it('toggling "show archived" re-requests the list with archived=true and renders the archived account (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([SHARED_ACCOUNT]);
    await fixture.whenStable();
    fixture.detectChanges();

    const toggle = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="show-archived-toggle"]',
    ) as HTMLInputElement;
    toggle.dispatchEvent(new Event('change'));

    const req = httpMock.expectOne((r) => r.url === '/api/accounts');
    expect(req.request.params.get('archived')).toBe('true');
    req.flush([ARCHIVED_ACCOUNT]);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Old Account');
  });

  it('submitting the create form calls POST /api/accounts with the exact body shape (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['name'].set('Savings');
    component['currency'].set('usd');
    component['exchangeRate'].set('1.5');
    component['initialFunds'].set('250.50');
    component['isPersonal'].set(true);
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/accounts');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Savings',
      currency: 'USD',
      exchange_rate: '1.5',
      initial_funds: '250.50',
      is_personal: true,
    });
    req.flush({ ...SHARED_ACCOUNT, name: 'Savings', is_personal: true });

    // createAccount() reloads the list afterwards.
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([]);
    await fixture.whenStable();
  });

  it('clicking archive calls PATCH /api/accounts/{id} with { archived: true }, never DELETE (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([SHARED_ACCOUNT]);
    await fixture.whenStable();
    fixture.detectChanges();

    const archiveButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Archive'));
    expect(archiveButton).toBeTruthy();
    archiveButton?.click();

    const req = httpMock.expectOne('/api/accounts/acc-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ archived: true });
    req.flush({ ...SHARED_ACCOUNT, archived: true });

    // archiveAccount() reloads the list afterwards.
    httpMock.expectOne((r) => r.url === '/api/accounts').flush([]);
    await fixture.whenStable();
  });
});
