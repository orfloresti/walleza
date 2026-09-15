/**
 * RED -> GREEN: `adminGuard` must block a non-platform-admin from
 * rendering the `/admin` area, even briefly (Phase 8 Unit 7, design
 * D110) — the real security boundary is the backend's
 * `require_platform_admin` dependency, but the frontend must not render
 * admin UI to a non-admin who navigates there directly. Mirrors
 * `auth.guard.spec.ts`'s pattern: real `HttpClient` against
 * `HttpTestingController`, no stubbed `AuthService`.
 */

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { UrlTree, provideRouter } from '@angular/router';
import type { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { Observable, firstValueFrom, isObservable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { adminGuard } from './admin.guard';
import { AuthService } from '../../core/auth/auth.service';

const DUMMY_ROUTE = {} as ActivatedRouteSnapshot;
const DUMMY_STATE = {} as RouterStateSnapshot;

describe('adminGuard', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('redirects an unauthenticated visitor to login and blocks the route', async () => {
    const authService = TestBed.inject(AuthService);
    const redirectSpy = vi
      .spyOn(authService, 'redirectToLogin')
      .mockImplementation((): void => undefined);

    const guardResult = TestBed.runInInjectionContext(() => adminGuard(DUMMY_ROUTE, DUMMY_STATE));
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock.expectOne('/api/me').flush('Unauthorized', {
      status: 401,
      statusText: 'Unauthorized',
    });

    const canActivate = await resultPromise;

    expect(canActivate).toBe(false);
    expect(redirectSpy).toHaveBeenCalledTimes(1);
  });

  it('redirects an authenticated non-admin away from /admin without rendering it', async () => {
    const guardResult = TestBed.runInInjectionContext(() => adminGuard(DUMMY_ROUTE, DUMMY_STATE));
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock
      .expectOne('/api/me')
      .flush({ id: 'user-1', email: 'user@example.com', is_platform_admin: false });

    const result = await resultPromise;

    expect(result).not.toBe(true);
    expect(result instanceof UrlTree).toBe(true);
  });

  it('allows a platform admin to reach /admin', async () => {
    const guardResult = TestBed.runInInjectionContext(() => adminGuard(DUMMY_ROUTE, DUMMY_STATE));
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock
      .expectOne('/api/me')
      .flush({ id: 'admin-1', email: 'admin@example.com', is_platform_admin: true });

    const canActivate = await resultPromise;

    expect(canActivate).toBe(true);
  });

  it('resolves isObservable for the returned guard result', async () => {
    const authService = TestBed.inject(AuthService);
    vi.spyOn(authService, 'redirectToLogin').mockImplementation((): void => undefined);

    const guardResult = TestBed.runInInjectionContext(() => adminGuard(DUMMY_ROUTE, DUMMY_STATE));
    expect(isObservable(guardResult)).toBe(true);
    const resultPromise = firstValueFrom(guardResult as Observable<boolean | UrlTree>);

    httpMock.expectOne('/api/me').flush('Unauthorized', {
      status: 401,
      statusText: 'Unauthorized',
    });

    await resultPromise;
  });
});
