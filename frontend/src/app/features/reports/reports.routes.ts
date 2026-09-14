import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `reports` feature (design D89) — a
 * single page hosting both the category-breakdown and trend charts, since
 * they share one filter bar (see `reports.page.ts`). No `new`/`:id/edit`
 * pair like `budgets.routes.ts`: reports are read-only views, not CRUD
 * resources.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/reports.page').then((m) => m.ReportsPage),
  },
];
