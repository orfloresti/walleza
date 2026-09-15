import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiCardComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AdminService, AdminStats } from '../data/admin.service';

/**
 * Admin dashboard/overview page (Phase 8 Unit 7, design D109/D110) —
 * renders `GET /api/admin/stats`'s aggregate counts and links to the
 * users, workspaces, and audit-log pages. This is the `/admin` index
 * route (see `admin.routes.ts`).
 */
@Component({
  selector: 'app-admin-dashboard-page',
  imports: [
    RouterLink,
    TranslocoPipe,
    UiAlertComponent,
    UiCardComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-3xl px-4 py-6">
      <ui-page-header titleKey="admin.dashboard.title" />

      @if (loading()) {
        <ui-loading messageKey="admin.dashboard.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="admin.dashboard.loadError" />
      } @else if (stats(); as s) {
        <ui-card testId="admin-stats">
          <ui-list>
            <ui-list-row>
              <ui-list-cell
                >{{ 'admin.dashboard.totalUsers' | transloco }}: {{ s.total_users }}</ui-list-cell
              >
            </ui-list-row>
            <ui-list-row>
              <ui-list-cell
                >{{ 'admin.dashboard.totalWorkspaces' | transloco }}:
                {{ s.total_workspaces }}</ui-list-cell
              >
            </ui-list-row>
            <ui-list-row>
              <ui-list-cell
                >{{ 'admin.dashboard.totalPlatformAdmins' | transloco }}:
                {{ s.total_platform_admins }}</ui-list-cell
              >
            </ui-list-row>
            <ui-list-row>
              <ui-list-cell
                >{{ 'admin.dashboard.deactivatedUsers' | transloco }}:
                {{ s.deactivated_users }}</ui-list-cell
              >
            </ui-list-row>
            <ui-list-row>
              <ui-list-cell
                >{{ 'admin.dashboard.deactivatedWorkspaces' | transloco }}:
                {{ s.deactivated_workspaces }}</ui-list-cell
              >
            </ui-list-row>
          </ui-list>
        </ui-card>
      }

      <nav class="mt-4 flex flex-wrap gap-4" aria-label="Admin sections">
        <a routerLink="/admin/users" class="text-on-surface hover:text-primary">{{
          'admin.nav.users' | transloco
        }}</a>
        <a routerLink="/admin/workspaces" class="text-on-surface hover:text-primary">{{
          'admin.nav.workspaces' | transloco
        }}</a>
        <a routerLink="/admin/audit" class="text-on-surface hover:text-primary">{{
          'admin.nav.audit' | transloco
        }}</a>
      </nav>
    </section>
  `,
})
export class AdminDashboardPage {
  private readonly adminService = inject(AdminService);

  protected readonly stats = signal<AdminStats | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.adminService.getStats().subscribe({
      next: (stats) => {
        this.loading.set(false);
        this.stats.set(stats);
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }
}
