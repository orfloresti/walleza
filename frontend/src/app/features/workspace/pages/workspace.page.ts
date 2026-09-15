import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import { AuthService } from '../../../core/auth/auth.service';
import {
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { AccountsService, type WorkspaceSummary } from '../../accounts/data/accounts.service';
import { AuditLogEntry, WorkspaceService } from '../data/workspace.service';

/** Detects Phase 8 design D106's deactivation-lockout 403 (`app/deps.py`'s
 * `require_membership`: `HTTPException(403, "workspace is deactivated")`).
 * Frontend-only judgment call (see class docstring): the backend does not
 * (yet) expose `is_active` on `GET /api/workspace`, so the read-only
 * banner is driven reactively by this exact rejection instead of a
 * proactively-fetched flag. */
function isDeactivatedWorkspaceError(error: unknown): boolean {
  return (
    error instanceof HttpErrorResponse &&
    error.status === 403 &&
    error.error?.detail === 'workspace is deactivated'
  );
}

/**
 * Basic workspace/members view (Phase 1 PR4 scope, task 7.2): renders
 * the `GET /api/workspace` get-or-create response (design D13 — no
 * onboarding chooser screen, this page IS the first load), lets a
 * member generate a shareable invite link (design D12) and remove
 * another member (design D15). PR4b (task 8.3) adds the
 * `GET /api/workspace/summary` per-currency/grand-total rendering here,
 * per design's own File Changes table ("frontend/.../workspace.page.ts |
 * Modify | ... `/summary` totals"). Account list/CRUD itself lives in
 * `features/accounts/` (PR4b's own feature module), not this page.
 *
 * Phase UI (PR7) — migrated to the `shared/ui/` kit. Member rows and the
 * per-currency summary rows both use `ui-list`/`ui-list-row`/
 * `ui-list-cell`; loading/error branches use `ui-loading`/`ui-alert`
 * exactly like every other migrated list page.
 *
 * **Judgment call (documented per PR5's `join.page.ts` / PR6's
 * `categories-list.page.ts` precedent of leaving undocumented gaps
 * explicit rather than forcing a component fit)**: neither the invite
 * URL text (`invite-url`) nor the summary grand total
 * (`summary-grand-total`) has a dedicated kit "value display" component
 * — the kit only offers structural containers (`ui-card`, `ui-list*`),
 * status components (`ui-loading`/`ui-alert`/`ui-empty-state`) and form
 * controls, none of which fit a single translated label + raw value
 * line. Both stay plain native `<p data-testid="…">` elements styled with
 * Tailwind utilities directly, matching invariant 1 (the testid stays on
 * the same kind of native element it was on before migration — here, no
 * migration of the element at all, since no kit component exists for it).
 *
 * **Phase 8 (PR6, design D110) owner-only controls**, added on top of the
 * migrated page above:
 * - Each member row shows its `role` (design D93/D109 `MemberOut.role`).
 *   `removeMember` is gated to `your_role === 'owner'` (design D109:
 *   `DELETE /api/workspace/members/{user_id}` is now `require_owner`
 *   server-side — a plain member would get a 403 today, so hiding the
 *   control client-side is UX only, matching D110's stated contract).
 * - **Transfer ownership** (owner-only, design D95/D109): a two-step
 *   in-page confirm (`ui-select` a target member, then a distinct
 *   "confirm transfer" step) rather than `window.confirm` — no existing
 *   page in this codebase uses native `confirm()`, and it is awkward to
 *   assert against in the `HttpTestingController` spec pattern every
 *   other page test here follows.
 * - **Audit log** (owner-only, design D105/O3): `GET /api/workspace/audit`
 *   fetched only when `your_role === 'owner'`, rendered as a flat list of
 *   `action` / `created_at` / actor rows including platform-admin actions
 *   recorded against this workspace.
 * - **Deactivated read-only banner** (design D106/D110): see
 *   `isDeactivatedWorkspaceError()` above — the backend's
 *   `GET /api/workspace` response does not expose `is_active` today, so
 *   this banner is driven reactively by the exact 403 `require_membership`
 *   already raises for a non-safe method against a deactivated workspace,
 *   rather than a proactively-fetched flag. Once shown, it persists for
 *   the rest of the page's lifetime (it does not clear itself — the
 *   underlying deactivation is a platform-admin action, not something an
 *   ordinary owner action can undo from this page).
 */
@Component({
  selector: 'app-workspace-page',
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
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-3xl px-4 py-6">
      <ui-page-header titleKey="workspace.title" />

      @if (readOnly()) {
        <ui-alert variant="warning" messageKey="workspace.readOnlyBanner" testId="workspace-readonly-banner" />
      }

      @if (loading()) {
        <ui-loading messageKey="workspace.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="workspace.loadError" />
      } @else if (workspace(); as ws) {
        <ui-card>
          <h2 class="text-lg font-semibold text-on-surface">{{ ws.name }}</h2>
          <p data-testid="your-role" class="text-sm text-on-surface-muted">
            {{ 'workspace.yourRole' | transloco }}: {{ 'workspace.role.' + ws.your_role | transloco }}
          </p>

          <ui-list testId="workspace-members" class="mt-3">
            @for (member of ws.members; track member.user_id) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ member.email }}</span>
                  <span class="ml-1 text-xs text-on-surface-muted">({{ 'workspace.role.' + member.role | transloco }})</span>
                </ui-list-cell>
                @if (isOwner() && member.user_id !== currentUserId()) {
                  <ui-list-cell class="md:ml-auto">
                    <ui-button variant="secondary" size="sm" (click)="removeMember(member.user_id)">
                      {{ 'workspace.removeMember' | transloco }}
                    </ui-button>
                  </ui-list-cell>
                }
              </ui-list-row>
            }
          </ui-list>

          <ui-button variant="primary" (click)="generateInvite()" class="mt-3">
            {{ 'workspace.generateInvite' | transloco }}
          </ui-button>

          @if (inviteUrl(); as url) {
            <p data-testid="invite-url" class="mt-2 text-sm text-on-surface-muted">{{ url }}</p>
          }
        </ui-card>

        @if (actionErrorKey(); as key) {
          <ui-alert [messageKey]="key" class="mt-3" />
        }

        @if (isOwner() && otherMemberOptions().length > 0) {
          <ui-card testId="transfer-ownership" class="mt-4">
            <h2 class="text-lg font-semibold text-on-surface">
              {{ 'workspace.transferOwnership' | transloco }}
            </h2>

            <ui-select
              testId="transfer-ownership-select"
              [options]="otherMemberOptions()"
              [(value)]="selectedNewOwnerId"
              placeholderKey="workspace.transferOwnershipSelectPlaceholder"
              class="mt-2 block"
            />

            @if (!confirmingTransfer()) {
              <ui-button
                variant="secondary"
                class="mt-2"
                [disabled]="!selectedNewOwnerId()"
                (click)="confirmingTransfer.set(true)"
              >
                {{ 'workspace.transferOwnership' | transloco }}
              </ui-button>
            } @else {
              <div class="mt-2 flex items-center gap-2">
                <ui-alert variant="warning" messageKey="workspace.transferOwnershipConfirm" />
              </div>
              <div class="mt-2 flex gap-2">
                <ui-button variant="danger" size="sm" (click)="transferOwnership()">
                  {{ 'workspace.transferOwnershipConfirmAction' | transloco }}
                </ui-button>
                <ui-button variant="secondary" size="sm" (click)="confirmingTransfer.set(false)">
                  {{ 'workspace.transferOwnershipCancel' | transloco }}
                </ui-button>
              </div>
            }

            @if (transferErrorKey(); as key) {
              <ui-alert [messageKey]="key" class="mt-2" />
            }
          </ui-card>
        }

        @if (isOwner()) {
          <ui-card testId="audit-log" class="mt-4">
            <h2 class="text-lg font-semibold text-on-surface">{{ 'workspace.auditLog.title' | transloco }}</h2>

            @if (auditLoading()) {
              <ui-loading messageKey="workspace.auditLog.loading" />
            } @else if (auditError()) {
              <ui-alert messageKey="workspace.auditLog.loadError" />
            } @else {
              <ui-list testId="audit-log-entries" class="mt-3">
                @for (entry of auditLog(); track entry.id) {
                  <ui-list-row>
                    <ui-list-cell>
                      <span>{{ entry.action }}</span>
                      <span class="ml-1 text-xs text-on-surface-muted">{{ entry.created_at }}</span>
                    </ui-list-cell>
                  </ui-list-row>
                } @empty {
                  <p data-testid="audit-log-empty" class="text-sm text-on-surface-muted">
                    {{ 'workspace.auditLog.empty' | transloco }}
                  </p>
                }
              </ui-list>
            }
          </ui-card>
        }
      }

      @if (summary(); as s) {
        <ui-card testId="summary" class="mt-4">
          <h2 class="text-lg font-semibold text-on-surface">{{ 'summary.title' | transloco }}</h2>
          <ui-list class="mt-3">
            @for (row of s.by_currency; track row.currency) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ row.currency }}: {{ row.total }}</span>
                </ui-list-cell>
              </ui-list-row>
            }
          </ui-list>
          <p data-testid="summary-grand-total" class="mt-2 font-medium text-on-surface">
            {{ 'summary.grandTotal' | transloco }}: {{ s.grand_total }}
          </p>
        </ui-card>
      } @else if (summaryError()) {
        <ui-alert messageKey="summary.loadError" class="mt-4" />
      }
    </section>
  `,
})
export class WorkspacePage {
  private readonly workspaceService = inject(WorkspaceService);
  private readonly accountsService = inject(AccountsService);
  private readonly authService = inject(AuthService);

  protected readonly workspace = this.workspaceService.workspace;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly inviteUrl = signal<string | null>(null);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly summary = signal<WorkspaceSummary | null>(null);
  protected readonly summaryError = signal(false);

  /** Phase 8 design D106/D110 — see `isDeactivatedWorkspaceError()` above
   * for why this is reactive rather than proactively fetched. */
  protected readonly readOnly = signal(false);

  protected readonly isOwner = computed(() => this.workspace()?.your_role === 'owner');

  protected readonly otherMemberOptions = computed<UiSelectOption[]>(() => {
    const ws = this.workspace();
    if (!ws) {
      return [];
    }
    return ws.members
      .filter((m) => m.user_id !== this.currentUserId())
      .map((m) => ({ value: m.user_id, label: m.email }));
  });

  protected readonly selectedNewOwnerId = signal('');
  protected readonly confirmingTransfer = signal(false);
  protected readonly transferErrorKey = signal<string | null>(null);

  protected readonly auditLog = signal<AuditLogEntry[]>([]);
  protected readonly auditLoading = signal(false);
  protected readonly auditError = signal(false);

  constructor() {
    this.load();
    this.loadSummary();
  }

  private loadSummary(): void {
    this.summaryError.set(false);
    this.accountsService.getSummary().subscribe({
      next: (summary) => this.summary.set(summary),
      error: () => this.summaryError.set(true),
    });
  }

  protected currentUserId(): string | null {
    return this.authService.user()?.id ?? null;
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.workspaceService.getWorkspace().subscribe({
      next: () => {
        this.loading.set(false);
        if (this.isOwner()) {
          this.loadAuditLog();
        }
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  private loadAuditLog(): void {
    this.auditLoading.set(true);
    this.auditError.set(false);
    this.workspaceService.getAuditLog().subscribe({
      next: (entries) => {
        this.auditLoading.set(false);
        this.auditLog.set(entries);
      },
      error: () => {
        this.auditLoading.set(false);
        this.auditError.set(true);
      },
    });
  }

  protected generateInvite(): void {
    this.actionErrorKey.set(null);
    this.workspaceService.createInvite().subscribe({
      next: (invite) => this.inviteUrl.set(`${window.location.origin}${invite.url}`),
      error: (err: unknown) => {
        if (isDeactivatedWorkspaceError(err)) {
          this.readOnly.set(true);
        }
        this.actionErrorKey.set('workspace.inviteError');
      },
    });
  }

  protected removeMember(userId: string): void {
    this.actionErrorKey.set(null);
    this.workspaceService.removeMember(userId).subscribe({
      next: () => this.load(),
      error: (err: unknown) => {
        if (isDeactivatedWorkspaceError(err)) {
          this.readOnly.set(true);
        }
        this.actionErrorKey.set('workspace.removeMemberError');
      },
    });
  }

  protected transferOwnership(): void {
    const newOwnerId = this.selectedNewOwnerId();
    if (!newOwnerId) {
      return;
    }
    this.transferErrorKey.set(null);
    this.workspaceService.transferOwnership(newOwnerId).subscribe({
      next: () => {
        this.confirmingTransfer.set(false);
        this.selectedNewOwnerId.set('');
        this.load();
      },
      error: (err: unknown) => {
        if (isDeactivatedWorkspaceError(err)) {
          this.readOnly.set(true);
        }
        this.transferErrorKey.set('workspace.transferOwnershipError');
      },
    });
  }
}
