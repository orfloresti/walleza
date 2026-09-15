import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { switchMap } from 'rxjs';

import { AuthService } from '../../core/auth/auth.service';

/**
 * Guards the `/admin` area (Phase 8 Unit 7, design D110). The `/admin`
 * route is deliberately NOT in the main nav (see `app.html`) — it is
 * reachable only by direct URL. That omission alone is not a security
 * boundary, so this guard still redirects away a non-admin who navigates
 * there directly, mirroring the backend's own `require_platform_admin`
 * 403 behavior: the real authorization boundary always stays server-side
 * (every `/api/admin/*` request re-resolves platform-admin status from
 * the database), and `is_platform_admin` here is only a rendering hint
 * — forging it client-side still yields 403s from the backend, it just
 * also skips rendering the admin shell in the first place.
 *
 * Waits for `AuthService.ensureAuthenticated()` first (an unauthenticated
 * visitor is redirected to login, same as `authGuard`), then checks the
 * resolved user's `is_platform_admin` flag; a non-admin is redirected to
 * `/` rather than shown even a flash of the admin shell.
 */
export const adminGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return authService.ensureAuthenticated().pipe(
    switchMap((authenticated) => {
      if (!authenticated) {
        authService.redirectToLogin();
        return [false as const];
      }
      const allowed = authService.user()?.is_platform_admin === true;
      return [allowed ? (true as const) : router.parseUrl('/')];
    }),
  );
};
