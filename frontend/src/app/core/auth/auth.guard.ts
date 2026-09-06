import { inject } from '@angular/core';
import { CanActivateFn } from '@angular/router';
import { map, tap } from 'rxjs';

import { AuthService } from './auth.service';

/**
 * Blocks navigation to a non-public route until authentication
 * completes (spec `authentication` / "Frontend Route Guard"). Waits for
 * `AuthService.ensureAuthenticated()` — the real `GET /api/me` round
 * trip — before deciding; an unauthenticated visitor is redirected to
 * the backend-driven Google login flow and never sees the guarded
 * route render.
 */
export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);

  return authService.ensureAuthenticated().pipe(
    tap((authenticated) => {
      if (!authenticated) {
        authService.redirectToLogin();
      }
    }),
    map((authenticated) => authenticated),
  );
};
