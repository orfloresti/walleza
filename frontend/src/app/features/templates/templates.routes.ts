import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `templates` feature (design D17/D56).
 * Mounted behind `authGuard` at the parent level in `app.routes.ts` — no
 * route in this array needs its own guard.
 *
 * `''` is the list (with an inline apply action per row), `'new'` and
 * `':id/edit'` both load the SAME `TemplateFormPage` (create vs. edit is
 * determined by whether an `id` route param is present, mirroring
 * `transactions.routes.ts`'s precedent).
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/templates-list.page').then((m) => m.TemplatesListPage),
  },
  {
    path: 'new',
    loadComponent: () =>
      import('./pages/template-form.page').then((m) => m.TemplateFormPage),
  },
  {
    path: ':id/edit',
    loadComponent: () =>
      import('./pages/template-form.page').then((m) => m.TemplateFormPage),
  },
];
