import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

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
 */
@Component({
  selector: 'app-join-page',
  imports: [TranslocoPipe],
  template: `
    <section>
      @switch (status()) {
        @case ('pending') {
          <p>{{ 'join.pending' | transloco }}</p>
        }
        @case ('success') {
          <p>{{ 'join.success' | transloco }}</p>
        }
        @case ('invalid') {
          <p role="alert">{{ 'join.invalid' | transloco }}</p>
        }
        @case ('conflict') {
          <p role="alert">{{ 'join.conflict' | transloco }}</p>
        }
        @case ('error') {
          <p role="alert">{{ 'join.error' | transloco }}</p>
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
