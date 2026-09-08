import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** `GET /api/workspace` member shape (design Interfaces/Contracts). */
export interface WorkspaceMember {
  user_id: string;
  email: string;
  joined_at: string;
}

/** `GET /api/workspace` -> 200 response shape (design D13 get-or-create;
 * this call also acts as the onboarding bootstrap — there is no separate
 * "create workspace" screen). */
export interface Workspace {
  id: string;
  name: string;
  members: WorkspaceMember[];
}

/** `POST /api/workspace/invites` -> 201 response (design D12 — the raw,
 * single-use invite token is embedded in `url` and returned exactly
 * once; it is never present in any later response). */
export interface InviteCreated {
  id: string;
  url: string;
  expires_at: string;
}

export const WORKSPACE_ENDPOINT = '/api/workspace';
export const WORKSPACE_INVITES_ENDPOINT = '/api/workspace/invites';
export const WORKSPACE_INVITE_ACCEPT_ENDPOINT = '/api/workspace/invites/accept';
export const WORKSPACE_MEMBERS_ENDPOINT = '/api/workspace/members';

/**
 * HTTP calls for the `workspace-membership` capability (design's
 * Interfaces/Contracts table), mirroring `AuthService`'s style: a
 * `signal`-based cache of the last-fetched workspace, `withCredentials`
 * on every call since the session lives in an httpOnly cookie (design
 * D8). Scoped to PR4 (workspace) — account endpoints belong to PR4b's
 * `features/accounts/data/accounts.service.ts`, not here.
 */
@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private readonly http = inject(HttpClient);

  private readonly workspaceSignal = signal<Workspace | null>(null);
  readonly workspace = this.workspaceSignal.asReadonly();

  /** `GET /api/workspace` — get-or-create bootstrap (design D13). Safe to
   * call on every load of the workspace/join pages; a brand-new user
   * gets a solo workspace created on the very first call. */
  getWorkspace(): Observable<Workspace> {
    return this.http
      .get<Workspace>(WORKSPACE_ENDPOINT, { withCredentials: true })
      .pipe(tap((workspace) => this.workspaceSignal.set(workspace)));
  }

  /** `POST /api/workspace/invites` — generates a shareable, single-use
   * invite link (design D12). */
  createInvite(): Observable<InviteCreated> {
    return this.http.post<InviteCreated>(WORKSPACE_INVITES_ENDPOINT, {}, { withCredentials: true });
  }

  /** `POST /api/workspace/invites/accept` — 204 on success, 404 for any
   * invalid/expired/already-consumed/revoked token, 409 when the
   * accepter's current workspace is not solo-and-empty (design D18/D20). */
  acceptInvite(token: string): Observable<void> {
    return this.http.post<void>(
      WORKSPACE_INVITE_ACCEPT_ENDPOINT,
      { token },
      { withCredentials: true },
    );
  }

  /** `DELETE /api/workspace/members/{user_id}` — removes another member,
   * or leaves the workspace if `userId` is the caller's own id (design
   * D15: deletes only the join row, the removed member's personal
   * accounts are retained). */
  removeMember(userId: string): Observable<void> {
    return this.http.delete<void>(`${WORKSPACE_MEMBERS_ENDPOINT}/${userId}`, {
      withCredentials: true,
    });
  }
}
