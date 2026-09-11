import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `recurring` feature (design D17/D56).
 * Mounted behind `authGuard` at the parent level in `app.routes.ts` — no
 * route in this array needs its own guard.
 *
 * `''` and `'subscriptions'` both load the SAME `RecurringListPage` —
 * design D56 is explicit that Subscriptions is a route rendering the same
 * list component with an `is_subscription=true` preset, NOT a second
 * entity, service, or route family. The preset is carried as static route
 * `data`, read by the page via `ActivatedRoute.snapshot.data` (design's
 * own "via route data" phrasing). `'new'` and `':id/edit'` both load the
 * SAME `RecurringFormPage` (create vs. edit is determined by whether an
 * `id` route param is present, mirroring `transactions.routes.ts`).
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/recurring-list.page').then((m) => m.RecurringListPage),
    data: { subscriptionsOnly: false },
  },
  {
    path: 'subscriptions',
    loadComponent: () =>
      import('./pages/recurring-list.page').then((m) => m.RecurringListPage),
    data: { subscriptionsOnly: true },
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./pages/recurring-form.page').then((m) => m.RecurringFormPage),
  },
  {
    path: ':id/edit',
    loadComponent: () =>
      import('./pages/recurring-form.page').then((m) => m.RecurringFormPage),
  },
];
