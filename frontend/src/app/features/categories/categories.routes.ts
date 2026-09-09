import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `categories` feature (design D17/D35).
 * Mounted behind `authGuard` at the parent level in `app.routes.ts` — no
 * route in this array needs its own guard. A single list page covers the
 * whole CRUD surface for this phase (list + create + delete), same
 * minimalism as `features/accounts/` (deliberately unpolished per the
 * proposal's scope).
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/categories-list.page').then((m) => m.CategoriesListPage),
  },
];
