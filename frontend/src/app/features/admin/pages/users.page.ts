import { Component, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AdminService, AdminUser } from '../data/admin.service';

/**
 * Platform-wide users list (Phase 8 Unit 7, design D109) — renders
 * `GET /api/admin/users`'s metadata-only rows (O1) and exposes
 * deactivate/reactivate plus grant/revoke platform-admin actions. Every
 * mutation re-fetches the list on success (mirrors `WorkspacePage`'s own
 * `load()`-after-mutation pattern) rather than optimistically patching
 * local state, to stay the single source of truth for `is_deactivated`/
 * `is_platform_admin`.
 */
@Component({
  selector: 'app-admin-users-page',
  imports: [
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-3xl px-4 py-6">
      <ui-page-header titleKey="admin.users.title" />

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" class="mt-2" />
      }

      @if (loading()) {
        <ui-loading messageKey="admin.users.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="admin.users.loadError" />
      } @else {
        <ui-card>
          <ui-list testId="admin-users">
            @for (user of users(); track user.id) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ user.email }}</span>
                  @if (user.is_deactivated) {
                    <span class="ml-1 text-xs text-danger">{{
                      'admin.users.deactivatedBadge' | transloco
                    }}</span>
                  }
                  @if (user.is_platform_admin) {
                    <span class="ml-1 text-xs text-primary">{{
                      'admin.users.platformAdminBadge' | transloco
                    }}</span>
                  }
                </ui-list-cell>
                <ui-list-cell class="md:ml-auto">
                  @if (user.is_deactivated) {
                    <ui-button variant="secondary" size="sm" (click)="reactivateUser(user.id)">
                      {{ 'admin.users.reactivate' | transloco }}
                    </ui-button>
                  } @else {
                    <ui-button variant="danger" size="sm" (click)="deactivateUser(user.id)">
                      {{ 'admin.users.deactivate' | transloco }}
                    </ui-button>
                  }
                  @if (user.is_platform_admin) {
                    <ui-button variant="secondary" size="sm" (click)="revokeAdmin(user.id)">
                      {{ 'admin.users.revokeAdmin' | transloco }}
                    </ui-button>
                  } @else {
                    <ui-button variant="secondary" size="sm" (click)="grantAdmin(user.id)">
                      {{ 'admin.users.grantAdmin' | transloco }}
                    </ui-button>
                  }
                </ui-list-cell>
              </ui-list-row>
            } @empty {
              <p class="text-sm text-on-surface-muted">{{ 'admin.users.empty' | transloco }}</p>
            }
          </ui-list>
        </ui-card>
      }
    </section>
  `,
})
export class AdminUsersPage {
  private readonly adminService = inject(AdminService);

  protected readonly users = signal<AdminUser[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.adminService.listUsers().subscribe({
      next: (users) => {
        this.loading.set(false);
        this.users.set(users);
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deactivateUser(userId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.deactivateUser(userId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.users.deactivateError'),
    });
  }

  protected reactivateUser(userId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.reactivateUser(userId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.users.reactivateError'),
    });
  }

  protected grantAdmin(userId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.grantAdmin(userId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.users.grantAdminError'),
    });
  }

  protected revokeAdmin(userId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.revokeAdmin(userId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.users.revokeAdminError'),
    });
  }
}
