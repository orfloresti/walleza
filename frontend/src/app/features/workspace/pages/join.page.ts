import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { UiAlertComponent, UiEmptyStateComponent, UiLoadingComponent } from '../../../shared/ui';
import { WorkspaceService } from '../data/workspace.service';

type JoinStatus = 'pending' | 'success' | 'invalid' | 'conflict' | 'error';

/**
 * `/join/:token` (Phase 1 PR4, task 7.4) — guarded by `authGuard` at the
 * parent route level in `app.routes.ts`, exactly like `workspace` and
 * `accounts` (design's frontend routing note: "join/:token behind
 * authGuard"). Deep-link preservation across the Google OAuth round
 * trip lives in the guard itself (`core/auth/post-login-redirect.ts`) —
 * by the time THIS component activates, the visitor is already known
 * to be authenticated.
 *
 * A brand-new user still has no `workspace_member` row at that point
 * (design D13's get-or-create only ever runs inside `GET /api/workspace`,
 * never as a side effect of login), and `POST /invites/accept` requires
 * one (design D14's `require_membership`, design D20's "current
 * workspace must be solo and empty" precondition) — so this page
 * bootstraps the caller's own solo workspace FIRST, then accepts the
 * invite.
 *
 * Phase UI (PR5) — migrated to the `shared/ui/` kit (D64-style structural
 * branching): `pending` renders `ui-loading`, `success` renders
 * `ui-empty-state` (the kit's only title+message container, reused here
 * as a completion card since no dedicated "success" component exists),
 * and `invalid`/`conflict`/`error` render `ui-alert variant="error"`
 * (matching the `role="alert"` each already carried).
 */
@Component({
  selector: 'app-join-page',
  imports: [UiLoadingComponent, UiEmptyStateComponent, UiAlertComponent],
  template: `
    <section class="mx-auto w-full max-w-md px-4 py-6">
      @switch (status()) {
        @case ('pending') {
          <ui-loading messageKey="join.pending" testId="join-pending" />
        }
        @case ('success') {
          <ui-empty-state
            testId="join-success"
            titleKey="join.successTitle"
            messageKey="join.success"
          />
        }
        @case ('invalid') {
          <ui-alert variant="error" messageKey="join.invalid" testId="join-invalid" />
        }
        @case ('conflict') {
          <ui-alert variant="error" messageKey="join.conflict" testId="join-conflict" />
        }
        @case ('error') {
          <ui-alert variant="error" messageKey="join.error" testId="join-error" />
        }
      }
    </section>
  `,
})
export class JoinPage {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly workspaceService = inject(WorkspaceService);

  protected readonly status = signal<JoinStatus>('pending');

  constructor() {
    const token = this.route.snapshot.paramMap.get('token');
    if (!token) {
      this.status.set('invalid');
      return;
    }
    this.bootstrapThenAccept(token);
  }

  private bootstrapThenAccept(token: string): void {
    this.workspaceService.getWorkspace().subscribe({
      next: () => this.acceptInvite(token),
      error: () => this.status.set('error'),
    });
  }

  private acceptInvite(token: string): void {
    this.workspaceService.acceptInvite(token).subscribe({
      next: () => {
        this.status.set('success');
        void this.router.navigateByUrl('/workspace');
      },
      error: (err: HttpErrorResponse) => {
        // Design D18: 404 for unknown/expired/already-accepted/revoked,
        // 409 when the accepter's current workspace is not solo-and-empty
        // (design D20) — every other failure is a generic error state.
        if (err.status === 404) {
          this.status.set('invalid');
        } else if (err.status === 409) {
          this.status.set('conflict');
        } else {
          this.status.set('error');
        }
      },
    });
  }
}
