import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `transfers` feature (design D17/D44).
 * Mounted behind `authGuard` at the parent level in `app.routes.ts` — no
 * route in this array needs its own guard.
 *
 * `''` is the list and `'new'` is the create-only form. There is
 * deliberately NO `:id/edit` route — design D43: a transfer has no
 * update endpoint at all (structural absence at every layer, proposal
 * T6). Correcting a transfer means deleting it and creating a new one.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/transfers-list.page').then((m) => m.TransfersListPage),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./pages/transfer-form.page').then((m) => m.TransferFormPage),
  },
];
