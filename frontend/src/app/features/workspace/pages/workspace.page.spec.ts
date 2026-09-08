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

const WORKSPACE_RESPONSE = {
  id: 'ws-1',
  name: "user@example.com's workspace",
  members: [
    { user_id: 'user-1', email: 'user@example.com', joined_at: '2026-01-01T00:00:00Z' },
    { user_id: 'user-2', email: 'peer@example.com', joined_at: '2026-01-02T00:00:00Z' },
  ],
};

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
    await fixture.whenStable();
  });
});
