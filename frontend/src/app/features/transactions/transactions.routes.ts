import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `transactions` feature (design
 * D17/D35). Mounted behind `authGuard` at the parent level in
 * `app.routes.ts` — no route in this array needs its own guard.
 *
 * `''` is the workspace-wide feed (not nested per-account, per the
 * design's legacy-screenshot-cited evidence); `new` and `:id/edit` both
 * load the SAME `TransactionFormPage` (create vs. edit is determined by
 * whether an `id` route param is present, mirroring how a single page
 * covers both modes elsewhere in this codebase's precedent of one page
 * per concern).
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/transactions-list.page').then((m) => m.TransactionsListPage),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./pages/transaction-form.page').then((m) => m.TransactionFormPage),
  },
  {
    path: ':id/edit',
    loadComponent: () =>
      import('./pages/transaction-form.page').then((m) => m.TransactionFormPage),
  },
];
