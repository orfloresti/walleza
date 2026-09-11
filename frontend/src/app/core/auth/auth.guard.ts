import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { Observable, map, of, switchMap } from 'rxjs';

import { AuthService } from './auth.service';
import { consumePostLoginRedirect, stashPostLoginRedirect } from './post-login-redirect';
import { Workspace, WorkspaceService } from '../../features/workspace/data/workspace.service';

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
 *
 * Workspace bootstrap (design D13's `GET /api/workspace` get-or-create):
 * every guarded route depends on `require_membership` (backend
 * `app/deps.py`), which 403s for a user with zero `workspace_member`
 * rows — and get-or-create is the ONLY thing that ever creates that
 * first row. Nothing else in the app calls it automatically, and `''`
 * redirects straight to `/accounts`, never `/workspace` — so without
 * this step here, a brand-new user is permanently stuck 403ing on
 * every page after their very first login. Cached via
 * `WorkspaceService.workspace()`'s own signal so this only round-trips
 * once per session, not on every navigation.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const authService = inject(AuthService);
  const workspaceService = inject(WorkspaceService);
  const router = inject(Router);

  return authService.ensureAuthenticated().pipe(
    switchMap((authenticated) => {
      if (!authenticated) {
        stashPostLoginRedirect(state.url);
        authService.redirectToLogin();
        return of(false);
      }

      const cachedWorkspace = workspaceService.workspace();
      const workspace$: Observable<Workspace> = cachedWorkspace
        ? of(cachedWorkspace)
        : workspaceService.getWorkspace();

      return workspace$.pipe(map(() => true));
    }),
    map((authenticatedAndBootstrapped) => {
      if (!authenticatedAndBootstrapped) {
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
