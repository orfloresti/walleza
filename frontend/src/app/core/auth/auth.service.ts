import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, shareReplay, tap } from 'rxjs';

/** Shape of the `GET /api/me` 200 response (design Interfaces/Contracts). */
export interface AuthUser {
  id: string;
  email: string;
}

/** `GET /api/me` -> 200 `{id,email}` | 401 (design Interfaces/Contracts). */
export const ME_ENDPOINT = '/api/me';

/** `GET /api/auth/login` -> 302 to Google (design Interfaces/Contracts). */
export const LOGIN_ENDPOINT = '/api/auth/login';

/**
 * Session state lives in an httpOnly cookie (design D8) — the browser
 * never holds a token it can read, so the only way to learn whether a
 * visitor is authenticated is to ask the backend via `GET /api/me`.
 * `withCredentials: true` is required so the browser attaches the
 * httpOnly session cookies to the request.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private readonly userSignal = signal<AuthUser | null>(null);
  private readonly authenticatedSignal = signal<boolean | null>(null);

  /** `null` until the first `/api/me` round trip resolves. */
  readonly user = this.userSignal.asReadonly();
  readonly authenticated = this.authenticatedSignal.asReadonly();

  private session$: Observable<boolean> | null = null;

  /**
   * Resolves once `GET /api/me` answers, caching the in-flight/settled
   * result so multiple guards checked during the same navigation only
   * hit the backend once.
   */
  ensureAuthenticated(): Observable<boolean> {
    if (!this.session$) {
      this.session$ = this.http.get<AuthUser>(ME_ENDPOINT, { withCredentials: true }).pipe(
        tap((user) => {
          this.userSignal.set(user);
          this.authenticatedSignal.set(true);
        }),
        map(() => true),
        catchError(() => {
          this.userSignal.set(null);
          this.authenticatedSignal.set(false);
          return of(false);
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.session$;
  }

  /**
   * Full-page navigation to the backend-driven Google OAuth login flow
   * (design D7 — FastAPI is the confidential OAuth client; there is no
   * Angular "/login" route to route to).
   */
  redirectToLogin(): void {
    window.location.href = LOGIN_ENDPOINT;
  }

  /** Drops the cached session result so the next guard re-checks `/api/me`. */
  resetSession(): void {
    this.session$ = null;
    this.userSignal.set(null);
    this.authenticatedSignal.set(null);
  }
}
