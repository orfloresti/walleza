import { Routes } from '@angular/router';

import { authGuard } from './core/auth/auth.guard';

/**
 * First real routes (design D17) — the previously empty `app.routes.ts`
 * and the first real `authGuard` wiring since Phase 0 PR4 implemented
 * it, unwired. `workspace`, `accounts`, `categories`, `transactions`,
 * and `transfers` are all lazy feature modules per D17's convention
 * (`features/<feature>/<feature>.routes.ts`); `join/:token` is a single
 * guarded page living under `features/workspace/` — every one of these
 * needs `authGuard` at the parent level (design's frontend routing note:
 * "join/:token behind authGuard").
 *
 * `''` redirects to `accounts` — design D35 explicitly keeps this
 * unchanged ("`''→'accounts'` redirect **unchanged**" — moving the
 * default landing page to the transaction feed is a product decision the
 * dashboard phase owns, not Phase 2's), and Phase 3's D44 keeps this
 * redirect unchanged again for the same reason. `categories`,
 * `transactions`, and `transfers` are added as peer lazy routes
 * alongside `accounts`/`workspace`, per each phase's own design File
 * Changes table entry for `app.routes.ts`. Phase 4's `templates` and
 * `recurring` (design D56) are added the same way — `recurring`'s child
 * routes ALSO define the Subscriptions view (`/recurring/subscriptions`),
 * so no separate `subscriptions` top-level path exists here.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'accounts' },
  {
    path: 'accounts',
    canActivate: [authGuard],
    loadChildren: () => import('./features/accounts/accounts.routes').then((m) => m.routes),
  },
  {
    path: 'categories',
    canActivate: [authGuard],
    loadChildren: () => import('./features/categories/categories.routes').then((m) => m.routes),
  },
  {
    path: 'transactions',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/transactions/transactions.routes').then((m) => m.routes),
  },
  {
    path: 'transfers',
    canActivate: [authGuard],
    loadChildren: () => import('./features/transfers/transfers.routes').then((m) => m.routes),
  },
  {
    path: 'templates',
    canActivate: [authGuard],
    loadChildren: () => import('./features/templates/templates.routes').then((m) => m.routes),
  },
  {
    path: 'recurring',
    canActivate: [authGuard],
    loadChildren: () => import('./features/recurring/recurring.routes').then((m) => m.routes),
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
