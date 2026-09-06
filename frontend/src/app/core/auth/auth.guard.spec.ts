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
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import type { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { Observable, firstValueFrom, isObservable } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { authGuard } from './auth.guard';
import { AuthService } from './auth.service';

const DUMMY_ROUTE = {} as ActivatedRouteSnapshot;
const DUMMY_STATE = {} as RouterStateSnapshot;

describe('authGuard', () => {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
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

    const canActivate = await resultPromise;

    expect(canActivate).toBe(true);
    expect(redirectSpy).not.toHaveBeenCalled();
  });
});
