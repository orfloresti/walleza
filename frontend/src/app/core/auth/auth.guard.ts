import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from './auth.service';
import { consumePostLoginRedirect, stashPostLoginRedirect } from './post-login-redirect';

/**
 * Blocks navigation to a non-public route until authentication
 * completes (spec `authentication` / "Frontend Route Guard"). Waits for
 * `AuthService.ensureAuthenticated()` — the real `GET /api/me` round
 * trip — before deciding; an unauthenticated visitor is redirected to
 * the backend-driven Google login flow and never sees the guarded
 * route render.
 *
 * Deep-link preservation (design's Phase 1 frontend routing note —
 * `/join/:token` and every other guarded route must survive the Google
 * OAuth round trip):
 * - Blocked (unauthenticated): the attempted URL (`state.url`) is
 *   stashed via `post-login-redirect.ts` before the full-page redirect
 *   to login, which would otherwise lose it.
 * - Allowed (authenticated) with a pending stash: instead of letting
 *   this navigation continue to its own destination, the guard replays
 *   the stashed URL as a `UrlTree` redirect and clears the stash, so a
 *   guarded deep link is restored exactly once after the post-login
 *   bootstrap completes. If the stash already equals the current
 *   attempted URL (the replay itself), it is left alone and the
 *   navigation proceeds normally.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return authService.ensureAuthenticated().pipe(
    map((authenticated) => {
      if (!authenticated) {
        stashPostLoginRedirect(state.url);
        authService.redirectToLogin();
        return false;
      }

      const pendingRedirect = consumePostLoginRedirect();
      if (pendingRedirect && pendingRedirect !== state.url) {
        return router.parseUrl(pendingRedirect);
      }

      return true;
    }),
  );
};
