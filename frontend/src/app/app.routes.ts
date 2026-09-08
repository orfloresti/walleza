import { Routes } from '@angular/router';

import { authGuard } from './core/auth/auth.guard';

/**
 * First real routes (design D17) — the previously empty `app.routes.ts`
 * and the first real `authGuard` wiring since Phase 0 PR4 implemented
 * it, unwired. `workspace` and `accounts` are both lazy feature modules
 * per D17's convention (`features/<feature>/<feature>.routes.ts`);
 * `join/:token` is a single guarded page living under
 * `features/workspace/` — every one of these needs `authGuard` at the
 * parent level (design's frontend routing note: "join/:token behind
 * authGuard").
 *
 * `''` redirects to `accounts` — design's final route shape (design's
 * "Frontend routes" line: "`''→'accounts'`, `accounts` and `workspace`
 * lazy `loadChildren` behind `authGuard`, `join/:token` behind
 * `authGuard`, `**→''`"). PR4 shipped an interim `''→'workspace'`
 * default because `accounts` did not exist yet; PR4b (this change)
 * completes the route shape now that it does.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'accounts' },
  {
    path: 'accounts',
    canActivate: [authGuard],
    loadChildren: () => import('./features/accounts/accounts.routes').then((m) => m.routes),
  },
  {
    path: 'workspace',
    canActivate: [authGuard],
    loadChildren: () => import('./features/workspace/workspace.routes').then((m) => m.routes),
  },
  {
    path: 'join/:token',
    canActivate: [authGuard],
    loadComponent: () => import('./features/workspace/pages/join.page').then((m) => m.JoinPage),
  },
  { path: '**', redirectTo: '' },
];
