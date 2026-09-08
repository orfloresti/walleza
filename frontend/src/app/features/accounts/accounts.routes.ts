import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `accounts` feature (design D17).
 * Mounted behind `authGuard` at the parent level in `app.routes.ts` —
 * no route in this array needs its own guard.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/accounts-list.page').then((m) => m.AccountsListPage),
  },
];
