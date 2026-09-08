import { Component, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import { AuthService } from '../../../core/auth/auth.service';
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
 * Deliberately unpolished — functionally correct, not styled.
 */
@Component({
  selector: 'app-workspace-page',
  imports: [TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'workspace.title' | transloco }}</h1>

      @if (loading()) {
        <p>{{ 'workspace.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'workspace.loadError' | transloco }}</p>
      } @else if (workspace(); as ws) {
        <h2>{{ ws.name }}</h2>

        <ul>
          @for (member of ws.members; track member.user_id) {
            <li>
              <span>{{ member.email }}</span>
              @if (member.user_id !== currentUserId()) {
                <button type="button" (click)="removeMember(member.user_id)">
                  {{ 'workspace.removeMember' | transloco }}
                </button>
              }
            </li>
          }
        </ul>

        <button type="button" (click)="generateInvite()">
          {{ 'workspace.generateInvite' | transloco }}
        </button>

        @if (inviteUrl(); as url) {
          <p data-testid="invite-url">{{ url }}</p>
        }

        @if (actionErrorKey(); as key) {
          <p role="alert">{{ key | transloco }}</p>
        }
      }

      @if (summary(); as s) {
        <section data-testid="summary">
          <h2>{{ 'summary.title' | transloco }}</h2>
          <ul>
            @for (row of s.by_currency; track row.currency) {
              <li>{{ row.currency }}: {{ row.total }}</li>
            }
          </ul>
          <p data-testid="summary-grand-total">
            {{ 'summary.grandTotal' | transloco }}: {{ s.grand_total }}
          </p>
        </section>
      } @else if (summaryError()) {
        <p role="alert">{{ 'summary.loadError' | transloco }}</p>
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
