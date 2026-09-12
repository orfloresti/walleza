/**
 * `JoinPage` — Phase 1 PR4 (task 7.4): `/join/:token`'s accept flow.
 * `authGuard` (tested separately in `core/auth/auth.guard.spec.ts`)
 * already guarantees the visitor is authenticated by the time this
 * component activates; these tests start from that point and prove the
 * page (a) bootstraps the caller's own workspace first (design D13 —
 * required before `POST /invites/accept` can succeed, design D14), then
 * (b) accepts the invite and maps the backend's D18 status codes to the
 * right on-screen state, navigating to `/workspace` on success.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { JoinPage } from './join.page';

const WORKSPACE_RESPONSE = {
  id: 'ws-1',
  name: "user@example.com's workspace",
  members: [{ user_id: 'user-1', email: 'user@example.com', joined_at: '2026-01-01T00:00:00Z' }],
};

function activatedRouteWithToken(token: string | null) {
  return {
    snapshot: { paramMap: convertToParamMap(token ? { token } : {}) },
  };
}

async function createFixture(token: string | null): Promise<ComponentFixture<JoinPage>> {
  await TestBed.configureTestingModule({
    imports: [
      JoinPage,
      TranslocoTestingModule.forRoot({
        langs: {
          en: {
            join: {
              pending: 'Joining the workspace…',
              successTitle: "You're in",
              success: 'You have joined the workspace.',
              invalid: 'This invite link is invalid or has expired.',
              conflict: 'Leave your current workspace before accepting a new invite.',
              error: 'Something went wrong.',
            },
          },
        },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: ActivatedRoute, useValue: activatedRouteWithToken(token) },
    ],
  }).compileComponents();

  return TestBed.createComponent(JoinPage);
}

describe('JoinPage', () => {
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  it('bootstraps the workspace, then accepts the invite, then navigates to /workspace on success', async () => {
    const fixture = await createFixture('rawtoken123');
    const router = TestBed.inject(Router);
    const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();

    const bootstrapReq = httpMock.expectOne('/api/workspace');
    expect(bootstrapReq.request.method).toBe('GET');
    bootstrapReq.flush(WORKSPACE_RESPONSE);
    await fixture.whenStable();

    const acceptReq = httpMock.expectOne('/api/workspace/invites/accept');
    expect(acceptReq.request.method).toBe('POST');
    expect(acceptReq.request.body).toEqual({ token: 'rawtoken123' });
    acceptReq.flush(null, { status: 204, statusText: 'No Content' });
    await fixture.whenStable();
    fixture.detectChanges();

    expect(navigateSpy).toHaveBeenCalledWith('/workspace');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'You have joined the workspace.',
    );
  });

  it('shows the invalid-invite state on a 404 from accept (design D18)', async () => {
    const fixture = await createFixture('badtoken');
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    await fixture.whenStable();

    httpMock
      .expectOne('/api/workspace/invites/accept')
      .flush('invite rejected', { status: 404, statusText: 'Not Found' });
    await fixture.whenStable();
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'This invite link is invalid or has expired.',
    );
  });

  it('shows the conflict state on a 409 from accept (design D20)', async () => {
    const fixture = await createFixture('conflicttoken');
    httpMock = TestBed.inject(HttpTestingController);

    fixture.detectChanges();
    httpMock.expectOne('/api/workspace').flush(WORKSPACE_RESPONSE);
    await fixture.whenStable();

    httpMock
      .expectOne('/api/workspace/invites/accept')
      .flush('conflict', { status: 409, statusText: 'Conflict' });
    await fixture.whenStable();
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'Leave your current workspace before accepting a new invite.',
    );
  });
});
