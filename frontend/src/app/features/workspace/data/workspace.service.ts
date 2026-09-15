import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** A workspace member's role (Phase 8 design D93/D109) — `'owner'` is
 * exactly one member per workspace (design D94), everyone else is
 * `'member'`. Used only for UI rendering decisions; the server re-checks
 * every owner-only action via `require_owner` regardless of what a
 * client sends or renders (design D110). */
export type WorkspaceRole = 'owner' | 'member';

/** `GET /api/workspace` member shape (design Interfaces/Contracts, role
 * added by Phase 8 design D93/D109 `MemberOut`). */
export interface WorkspaceMember {
  user_id: string;
  email: string;
  joined_at: string;
  role: WorkspaceRole;
}

/** `GET /api/workspace` -> 200 response shape (design D13 get-or-create;
 * this call also acts as the onboarding bootstrap — there is no separate
 * "create workspace" screen). `your_role` added by Phase 8 design D110 —
 * the caller's own role in this workspace, driving owner-only UI. */
export interface Workspace {
  id: string;
  name: string;
  members: WorkspaceMember[];
  your_role: WorkspaceRole;
}

/** `POST /api/workspace/invites` -> 201 response (design D12 — the raw,
 * single-use invite token is embedded in `url` and returned exactly
 * once; it is never present in any later response). */
export interface InviteCreated {
  id: string;
  url: string;
  expires_at: string;
}

/** `GET /api/workspace/audit` -> 200 row shape (Phase 8 design D102/D105
 * `AuditLogEntryOut`). Owner-only read of this workspace's audit trail,
 * including platform-admin actions recorded against it (product
 * decision O3). */
export interface AuditLogEntry {
  id: string;
  created_at: string;
  actor_user_id: string | null;
  actor_was_platform_admin: boolean;
  action: string;
  target_type: string;
  target_id: string | null;
  workspace_id: string | null;
  metadata: Record<string, unknown>;
}

export const WORKSPACE_ENDPOINT = '/api/workspace';
export const WORKSPACE_INVITES_ENDPOINT = '/api/workspace/invites';
export const WORKSPACE_INVITE_ACCEPT_ENDPOINT = '/api/workspace/invites/accept';
export const WORKSPACE_MEMBERS_ENDPOINT = '/api/workspace/members';
export const WORKSPACE_TRANSFER_OWNERSHIP_ENDPOINT = '/api/workspace/transfer-ownership';
export const WORKSPACE_AUDIT_ENDPOINT = '/api/workspace/audit';

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

  /** `DELETE /api/workspace/members/{user_id}` — owner-only removal of
   * ANOTHER member (design D109: self-removal targeting the caller's own
   * `user_id` is now a distinct 409-rejected path, see `leaveWorkspace()`
   * below). Deletes only the join row — the removed member's personal
   * accounts are retained (design D15). */
  removeMember(userId: string): Observable<void> {
    return this.http.delete<void>(`${WORKSPACE_MEMBERS_ENDPOINT}/${userId}`, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/workspace/members/me` — self-removal, open to any
   * member (design D109 "Self-Removal Is a Distinct Path"). 409 if the
   * caller is the sole owner and other members remain (design D95). */
  leaveWorkspace(): Observable<void> {
    return this.http.delete<void>(`${WORKSPACE_MEMBERS_ENDPOINT}/me`, {
      withCredentials: true,
    });
  }

  /** `POST /api/workspace/transfer-ownership` — owner-only, atomic
   * demote-self/promote-target handover (design D95/D109). */
  transferOwnership(newOwnerUserId: string): Observable<void> {
    return this.http.post<void>(
      WORKSPACE_TRANSFER_OWNERSHIP_ENDPOINT,
      { new_owner_user_id: newOwnerUserId },
      { withCredentials: true },
    );
  }

  /** `GET /api/workspace/audit` — owner-only read of this workspace's
   * audit trail (design D105), including platform-admin actions recorded
   * against it (product decision O3). */
  getAuditLog(): Observable<AuditLogEntry[]> {
    return this.http.get<AuditLogEntry[]>(WORKSPACE_AUDIT_ENDPOINT, { withCredentials: true });
  }
}
