/**
 * RED -> GREEN: the frontend route guard MUST block navigation to a
 * guarded route until authentication completes (spec `authentication` /
 * "Frontend Route Guard"; design D8 — session lives in an httpOnly
 * cookie, so the guard can only learn the auth state by asking the
 * backend via `GET /api/me`, per the design's Interfaces/Contracts
 * table: 200 `{id,email}` | 401).
 *
 * These tests exercise the actual guard function against a mocked
 * `HttpClient` (via `HttpTestingController`), not a stubbed
 * `AuthService` — this proves the guard genuinely waits for the
 * `/api/me` round trip before deciding, rather than assuming a
 * synchronous/pre-known auth state.
 *
 * Phase 1 PR4 (tasks 7.1/7.3) extends this file: the same `authGuard`
 * is what now protects `/workspace`, `/accounts` (PR4b), and
 * `/join/:token` — the deep-link stash/consume tests below prove the
 * generic mechanism `/join/:token` relies on to survive the Google
 * OAuth round trip (design's Phase 1 frontend routing note).
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, UrlTree, provideRouter } from '@angular/router';
import type { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { Observable, firstValueFrom, isObservable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { authGuard } from './auth.guard';
import { AuthService } from './auth.service';

const DUMMY_ROUTE = {} as ActivatedRouteSnapshot;
const DUMMY_STATE = {} as RouterStateSnapshot;
const POST_LOGIN_REDIRECT_KEY = 'walleza.postLoginRedirect';

describe('authGuard', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    sessionStorage.removeItem(POST_LOGIN_REDIRECT_KEY);
  });

  it('redirects an unauthenticated direct navigation to a guarded route and blocks it', async () => {
    const authService = TestBed.inject(AuthService);
    const redirectSpy = vi
      .spyOn(authService, 'redirectToLogin')
      .mockImplementation((): void => undefined);

    const guardResult = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, DUMMY_STATE),
    );
    expect(isObservable(guardResult)).toBe(true);
    const resultPromise = firstValueFrom(guardResult as Observable<boolean>);

    httpMock.expectOne('/api/me').flush('Unauthorized', {
      status: 401,
      statusText: 'Unauthorized',
    });

    const canActivate = await resultPromise;

    expect(canActivate).toBe(false);
    expect(redirectSpy).toHaveBeenCalledTimes(1);
  });

  it('allows navigation to a guarded route once /api/me confirms a session', async () => {
    const authService = TestBed.inject(AuthService);
    const redirectSpy = vi
      .spyOn(authService, 'redirectToLogin')
      .mockImplementation((): void => undefined);

    const guardResult = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, DUMMY_STATE),
    );
    const resultPromise = firstValueFrom(guardResult as Observable<boolean>);

    httpMock.expectOne('/api/me').flush({ id: 'user-1', email: 'user@example.com' });
    httpMock
      .expectOne('/api/workspace')
      .flush({ id: 'ws-1', name: 'Solo', members: [] });

    const canActivate = await resultPromise;

    expect(canActivate).toBe(true);
    expect(redirectSpy).not.toHaveBeenCalled();
  });

  it('does not re-fetch the workspace on a second guarded navigation in the same session (cached via the workspace signal, mirroring AuthService.ensureAuthenticated\'s own /api/me caching)', async () => {
    const guardResult1 = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, DUMMY_STATE),
    );
    const resultPromise1 = firstValueFrom(guardResult1 as Observable<boolean>);
    httpMock.expectOne('/api/me').flush({ id: 'user-1', email: 'user@example.com' });
    httpMock
      .expectOne('/api/workspace')
      .flush({ id: 'ws-1', name: 'Solo', members: [] });
    await resultPromise1;

    const guardResult2 = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, { url: '/transactions' } as RouterStateSnapshot),
    );
    const canActivate = await firstValueFrom(guardResult2 as Observable<boolean>);

    // Neither /api/me nor /api/workspace fire again — AuthService's own
    // shareReplay caches the first, and the guard's cachedWorkspace check
    // (workspaceService.workspace()) short-circuits the second.
    httpMock.verify();
    expect(canActivate).toBe(true);
  });

  it('stashes the attempted URL before redirecting an unauthenticated visitor to login (deep-link preservation, task 7.1/7.4)', async () => {
    const authService = TestBed.inject(AuthService);
    vi.spyOn(authService, 'redirectToLogin').mockImplementation((): void => undefined);
    const joinAttempt = { url: '/join/abc123' } as RouterStateSnapshot;

    const guardResult = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, joinAttempt),
    );
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock.expectOne('/api/me').flush('Unauthorized', {
      status: 401,
      statusText: 'Unauthorized',
    });
    await resultPromise;

    expect(sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY)).toBe('/join/abc123');
  });

  it('replays the stashed URL as a redirect once authentication succeeds, and clears the stash', async () => {
    sessionStorage.setItem(POST_LOGIN_REDIRECT_KEY, '/join/abc123');
    const router = TestBed.inject(Router);
    const postLoginAttempt = { url: '/workspace' } as RouterStateSnapshot;

    const guardResult = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, postLoginAttempt),
    );
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock.expectOne('/api/me').flush({ id: 'user-1', email: 'user@example.com' });
    httpMock
      .expectOne('/api/workspace')
      .flush({ id: 'ws-1', name: 'Solo', members: [] });
    const result = await resultPromise;

    expect(result).toBeInstanceOf(UrlTree);
    expect(router.serializeUrl(result as UrlTree)).toBe('/join/abc123');
    expect(sessionStorage.getItem(POST_LOGIN_REDIRECT_KEY)).toBeNull();
  });

  it('does not redirect when the stashed URL is already the current attempted URL (the replay itself)', async () => {
    sessionStorage.setItem(POST_LOGIN_REDIRECT_KEY, '/join/abc123');
    const replayAttempt = { url: '/join/abc123' } as RouterStateSnapshot;

    const guardResult = TestBed.runInInjectionContext(() =>
      authGuard(DUMMY_ROUTE, replayAttempt),
    );
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock.expectOne('/api/me').flush({ id: 'user-1', email: 'user@example.com' });
    httpMock
      .expectOne('/api/workspace')
      .flush({ id: 'ws-1', name: 'Solo', members: [] });
    const result = await resultPromise;

    expect(result).toBe(true);
  });
});
