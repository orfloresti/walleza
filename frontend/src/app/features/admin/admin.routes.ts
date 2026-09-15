import { Routes } from '@angular/router';

/**
 * Lazy-loaded child routes for the `admin` feature (Phase 8 Unit 7,
 * design D110). Mounted at `/admin` in `app.routes.ts` behind
 * `adminGuard` at the parent level — deliberately NOT added to the main
 * nav (`app.html`), this is a genuinely separate `/admin` area for the
 * platform-admin persona, reachable only by direct URL.
 */
export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./pages/dashboard.page').then((m) => m.AdminDashboardPage),
  },
  {
    path: 'users',
    loadComponent: () => import('./pages/users.page').then((m) => m.AdminUsersPage),
  },
  {
    path: 'workspaces',
    loadComponent: () => import('./pages/workspaces.page').then((m) => m.AdminWorkspacesPage),
  },
  {
    path: 'audit',
    loadComponent: () => import('./pages/audit.page').then((m) => m.AdminAuditPage),
  },
];
