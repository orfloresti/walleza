import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `budgets` feature (design's Frontend
 * Shape section). Mounted behind `authGuard` at the parent level in
 * `app.routes.ts`. `'new'` and `':id/edit'` both load the SAME
 * `BudgetFormPage` (create vs. edit determined by whether an `id` route
 * param is present), mirroring `recurring.routes.ts`/`templates.routes.ts`.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/budgets-list.page').then((m) => m.BudgetsListPage),
  },
  {
    path: 'new',
    loadComponent: () => import('./pages/budget-form.page').then((m) => m.BudgetFormPage),
  },
  {
    path: ':id/edit',
    loadComponent: () => import('./pages/budget-form.page').then((m) => m.BudgetFormPage),
  },
];
