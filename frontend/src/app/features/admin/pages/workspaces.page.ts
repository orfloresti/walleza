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
import { AdminService, AdminWorkspace } from '../data/admin.service';

/**
 * Platform-wide workspaces list (Phase 8 Unit 7, design D109) — renders
 * `GET /api/admin/workspaces`'s metadata-only rows (name, member count,
 * `is_active`; O1) and exposes deactivate/reactivate actions (design
 * D106's read-only lockout).
 */
@Component({
  selector: 'app-admin-workspaces-page',
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
      <ui-page-header titleKey="admin.workspaces.title" />

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" class="mt-2" />
      }

      @if (loading()) {
        <ui-loading messageKey="admin.workspaces.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="admin.workspaces.loadError" />
      } @else {
        <ui-card>
          <ui-list testId="admin-workspaces">
            @for (workspace of workspaces(); track workspace.id) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ workspace.name }}</span>
                  <span class="ml-1 text-xs text-on-surface-muted"
                    >({{ workspace.member_count }})</span
                  >
                  @if (!workspace.is_active) {
                    <span class="ml-1 text-xs text-danger">{{
                      'admin.workspaces.deactivatedBadge' | transloco
                    }}</span>
                  }
                </ui-list-cell>
                <ui-list-cell class="md:ml-auto">
                  @if (workspace.is_active) {
                    <ui-button
                      variant="danger"
                      size="sm"
                      (click)="deactivateWorkspace(workspace.id)"
                    >
                      {{ 'admin.workspaces.deactivate' | transloco }}
                    </ui-button>
                  } @else {
                    <ui-button
                      variant="secondary"
                      size="sm"
                      (click)="reactivateWorkspace(workspace.id)"
                    >
                      {{ 'admin.workspaces.reactivate' | transloco }}
                    </ui-button>
                  }
                </ui-list-cell>
              </ui-list-row>
            } @empty {
              <p class="text-sm text-on-surface-muted">{{
                'admin.workspaces.empty' | transloco
              }}</p>
            }
          </ui-list>
        </ui-card>
      }
    </section>
  `,
})
export class AdminWorkspacesPage {
  private readonly adminService = inject(AdminService);

  protected readonly workspaces = signal<AdminWorkspace[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.adminService.listWorkspaces().subscribe({
      next: (workspaces) => {
        this.loading.set(false);
        this.workspaces.set(workspaces);
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected deactivateWorkspace(workspaceId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.deactivateWorkspace(workspaceId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.workspaces.deactivateError'),
    });
  }

  protected reactivateWorkspace(workspaceId: string): void {
    this.actionErrorKey.set(null);
    this.adminService.reactivateWorkspace(workspaceId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('admin.workspaces.reactivateError'),
    });
  }
}
