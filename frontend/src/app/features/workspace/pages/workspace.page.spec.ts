/**
 * `WorkspacePage` — Phase 1 PR4 (task 7.2), "basic workspace/members
 * view" scope: renders the `GET /api/workspace` response, generates an
 * invite link, and removes a member. PR4b (task 8.3/8.4) extends this
 * file: the page now also fires `GET /api/workspace/summary` on
 * construction and renders its per-currency totals + grand total; every
 * pre-existing test below flushes that additional request so
 * `httpMock.verify()` does not see it as outstanding. Real `HttpClient`
 * against `HttpTestingController`, no live backend — same pattern as
 * `auth.guard.spec.ts` and `workspace.service.spec.ts`.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { WorkspacePage } from './workspace.page';

/** Owner fixture (`your_role: 'owner'`) — the caller (`user-1`) owns the
 * workspace, `user-2` is a plain member (Phase 8 design D93/D109/D110). */
const WORKSPACE_RESPONSE = {
  id: 'ws-1',
  name: "user@example.com's workspace",
  members: [
    { user_id: 'user-1', email: 'user@example.com', joined_at: '2026-01-01T00:00:00Z', role: 'owner' },
    { user_id: 'user-2', email: 'peer@example.com', joined_at: '2026-01-02T00:00:00Z', role: 'member' },
  ],
  your_role: 'owner',
};

/** Member fixture — the caller (`user-2`) is a plain member of a
 * workspace owned by `user-1`. */
const MEMBER_WORKSPACE_RESPONSE = {
  id: 'ws-1',
  name: "user@example.com's workspace",
  members: [
    { user_id: 'user-1', email: 'user@example.com', joined_at: '2026-01-01T00:00:00Z', role: 'owner' },
    { user_id: 'user-2', email: 'peer@example.com', joined_at: '2026-01-02T00:00:00Z', role: 'member' },
  ],
  your_role: 'member',
};

const AUDIT_LOG_RESPONSE = [
  {
    id: 'audit-1',
    created_at: '2026-01-03T00:00:00Z',
    actor_user_id: 'user-1',
    actor_was_platform_admin: false,
    action: 'workspace.renamed',
    target_type: 'workspace',
    target_id: 'ws-1',
    workspace_id: 'ws-1',
    metadata: {},
  },
];

const SUMMARY_RESPONSE = {
  by_currency: [
    { currency: 'USD', total: '350.50' },
    { currency: 'EUR', total: '10.00' },
  ],
  grand_total: '360.50',
};

describe('WorkspacePage', () => {
  let fixture: ComponentFixture<WorkspacePage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        WorkspacePage,
        TranslocoTestingModule.forRoot({
          langs: {
            en: {
              workspace: {
                title: 'Workspace',
                loading: 'Loading…',
                loadError: 'Could not load your workspace.',
                removeMember: 'Remove',
                generateInvite: 'Generate invite link',
                inviteError: 'Could not generate an invite link.',
                removeMemberError: 'Could not remove that member.',
                yourRole: 'Your role',
                role: { owner: 'Owner', member: 'Member' },
                readOnlyBanner: 'This workspace is deactivated and is currently read-only.',
                transferOwnership: 'Transfer ownership',
                transferOwnershipSelectPlaceholder: 'Select a member',
                transferOwnershipConfirm: 'This will transfer ownership.',
                transferOwnershipConfirmAction: 'Confirm transfer',
                transferOwnershipCancel: 'Cancel',
                transferOwnershipError: 'Could not transfer ownership.',
                auditLog: {
                  title: 'Audit log',
                  loading: 'Loading audit log…',
                  loadError: 'Could not load the audit log.',
                  empty: 'No audit events yet.',
                },
              },
              summary: {
                title: 'Summary',
                grandTotal: 'Grand total',
                loadError: 'Could not load the summary.',
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
    fixture = TestBed.createComponent(WorkspacePage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('loads and renders the workspace and its members on init', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('user@example.com');
    expect(text).toContain('peer@example.com');
  });

  it('renders per-currency totals and the grand total from GET /api/workspace/summary (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const summarySection = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="summary"]',
    );
    const text = summarySection?.textContent ?? '';
    expect(text).toContain('USD');
    expect(text).toContain('350.50');
    expect(text).toContain('EUR');
    expect(text).toContain('10.00');
    const grandTotal = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="summary-grand-total"]',
    );
    expect(grandTotal?.textContent).toContain('360.50');
  });

  it('generating an invite link renders the returned URL', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const generateButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Generate invite link'));
    expect(generateButton).toBeTruthy();
    generateButton?.click();

    httpMock
      .expectOne('/api/workspace/invites')
      .flush({ id: 'inv-1', url: '/join/rawtoken123', expires_at: '2026-01-08T00:00:00Z' });
    await fixture.whenStable();
    fixture.detectChanges();

    const rendered = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="invite-url"]',
    );
    expect(rendered?.textContent).toContain('/join/rawtoken123');
  });

  it('removing a member calls DELETE /api/workspace/members/{id} with the clicked member id (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const removeButtons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).filter((btn) => btn.textContent?.includes('Remove'));
    expect(removeButtons.length).toBe(2);
    removeButtons[1]?.click();

    const removeReq = httpMock.expectOne('/api/workspace/members/user-2');
    expect(removeReq.request.method).toBe('DELETE');
    removeReq.flush(null, { status: 204, statusText: 'No Content' });

    // removeMember() reloads the workspace afterwards.
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
  });

  it('a plain member does not see owner-only controls (role-conditional rendering)', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(MEMBER_WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    // No /api/workspace/audit request — a plain member's client never fetches it.
    await fixture.whenStable();
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    const removeButtons = Array.from(root.querySelectorAll('button')).filter((btn) =>
      btn.textContent?.includes('Remove'),
    );
    expect(removeButtons.length).toBe(0);
    expect(root.querySelector('[data-testid="transfer-ownership"]')).toBeNull();
    expect(root.querySelector('[data-testid="audit-log"]')).toBeNull();
    expect(root.textContent).toContain('Member');
  });

  it('an owner sees the transfer-ownership and audit-log controls', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-testid="transfer-ownership"]')).toBeTruthy();
    const auditSection = root.querySelector('[data-testid="audit-log"]');
    expect(auditSection).toBeTruthy();
    expect(auditSection?.textContent).toContain('workspace.renamed');
  });

  it('transfer-ownership flow: select a member, confirm, then POST the transfer', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    const select = root.querySelector(
      '[data-testid="transfer-ownership-select"]',
    ) as HTMLSelectElement;
    expect(select).toBeTruthy();
    select.value = 'user-2';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    const transferSection = root.querySelector('[data-testid="transfer-ownership"]') as HTMLElement;
    const transferButton = Array.from(transferSection.querySelectorAll('button')).find((btn) =>
      btn.textContent?.includes('Transfer ownership'),
    );
    transferButton?.click();
    fixture.detectChanges();

    const confirmButton = Array.from(transferSection.querySelectorAll('button')).find((btn) =>
      btn.textContent?.includes('Confirm transfer'),
    );
    expect(confirmButton).toBeTruthy();
    confirmButton?.click();

    const req = httpMock.expectOne('/api/workspace/transfer-ownership');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ new_owner_user_id: 'user-2' });
    req.flush(null, { status: 204, statusText: 'No Content' });

    // transferOwnership() reloads the workspace afterwards.
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
  });

  it('shows a persistent read-only banner when a mutation 403s because the workspace is deactivated', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    httpMock.expectOne('/api/workspace/summary').flush(SUMMARY_RESPONSE);
    httpMock.expectOne('/api/workspace/audit').flush(AUDIT_LOG_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[data-testid="workspace-readonly-banner"]')).toBeNull();

    const generateButton = Array.from(root.querySelectorAll('button')).find((btn) =>
      btn.textContent?.includes('Generate invite link'),
    );
    generateButton?.click();

    httpMock
      .expectOne('/api/workspace/invites')
      .flush(
        { detail: 'workspace is deactivated' },
        { status: 403, statusText: 'Forbidden' },
      );
    await fixture.whenStable();
    fixture.detectChanges();

    expect(root.querySelector('[data-testid="workspace-readonly-banner"]')).toBeTruthy();
  });
});
