import { Component, inject, signal } from '@angular/core';
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
import { AdminAuditLogEntry, AdminService } from '../data/admin.service';

/**
 * Platform-wide audit log view (Phase 8 Unit 7, design D105/O3) —
 * renders `GET /api/admin/audit`'s unfiltered, every-entry feed. Unlike
 * `WorkspacePage`'s owner-scoped audit view (limited to that workspace),
 * this is the platform admin's full view across every workspace and
 * every platform-level action.
 */
@Component({
  selector: 'app-admin-audit-page',
  imports: [
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
      <ui-page-header titleKey="admin.audit.title" />

      @if (loading()) {
        <ui-loading messageKey="admin.audit.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="admin.audit.loadError" />
      } @else {
        <ui-card>
          <ui-list testId="admin-audit-entries">
            @for (entry of entries(); track entry.id) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ entry.action }}</span>
                  <span class="ml-1 text-xs text-on-surface-muted">{{ entry.created_at }}</span>
                  @if (entry.workspace_id) {
                    <span class="ml-1 text-xs text-on-surface-muted">{{
                      entry.workspace_id
                    }}</span>
                  }
                </ui-list-cell>
              </ui-list-row>
            } @empty {
              <p data-testid="admin-audit-empty" class="text-sm text-on-surface-muted">
                {{ 'admin.audit.empty' | transloco }}
              </p>
            }
          </ui-list>
        </ui-card>
      }
    </section>
  `,
})
export class AdminAuditPage {
  private readonly adminService = inject(AdminService);

  protected readonly entries = signal<AdminAuditLogEntry[]>([]);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.adminService.getAuditLog().subscribe({
      next: (entries) => {
        this.loading.set(false);
        this.entries.set(entries);
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }
}
