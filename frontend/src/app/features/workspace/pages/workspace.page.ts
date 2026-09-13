import { Component, inject, signal } from '@angular/core';
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
} from '../../../shared/ui';
import { AccountsService, type WorkspaceSummary } from '../../accounts/data/accounts.service';
import { WorkspaceService } from '../data/workspace.service';

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
  ],
  template: `
    <section class="mx-auto w-full max-w-3xl px-4 py-6">
      <ui-page-header titleKey="workspace.title" />

      @if (loading()) {
        <ui-loading messageKey="workspace.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="workspace.loadError" />
      } @else if (workspace(); as ws) {
        <ui-card>
          <h2 class="text-lg font-semibold text-on-surface">{{ ws.name }}</h2>

          <ui-list testId="workspace-members" class="mt-3">
            @for (member of ws.members; track member.user_id) {
              <ui-list-row>
                <ui-list-cell>
                  <span>{{ member.email }}</span>
                </ui-list-cell>
                @if (member.user_id !== currentUserId()) {
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
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected generateInvite(): void {
    this.actionErrorKey.set(null);
    this.workspaceService.createInvite().subscribe({
      next: (invite) => this.inviteUrl.set(`${window.location.origin}${invite.url}`),
      error: () => this.actionErrorKey.set('workspace.inviteError'),
    });
  }

  protected removeMember(userId: string): void {
    this.actionErrorKey.set(null);
    this.workspaceService.removeMember(userId).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('workspace.removeMemberError'),
    });
  }
}
