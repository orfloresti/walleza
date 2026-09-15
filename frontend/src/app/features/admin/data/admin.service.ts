import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** `GET /api/admin/users` row shape (Phase 8 design D109 `AdminUserOut`).
 * Metadata-only (O1) — never a financial field. */
export interface AdminUser {
  id: string;
  email: string;
  created_at: string;
  workspace_id: string | null;
  workspace_name: string | null;
  is_platform_admin: boolean;
  is_deactivated: boolean;
}

/** `GET /api/admin/workspaces` row shape (design D109 `AdminWorkspaceOut`)
 * — counts, never content. */
export interface AdminWorkspace {
  id: string;
  name: string;
  created_at: string;
  member_count: number;
  is_active: boolean;
}

/** `GET /api/admin/stats` response shape (design D109 `AdminStatsOut`). */
export interface AdminStats {
  total_users: number;
  total_workspaces: number;
  total_platform_admins: number;
  deactivated_users: number;
  deactivated_workspaces: number;
}

/** `GET /api/admin/audit` row shape (design D102/D105 `AuditLogEntryOut`)
 * — every entry platform-wide, unfiltered. */
export interface AdminAuditLogEntry {
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

export const ADMIN_USERS_ENDPOINT = '/api/admin/users';
export const ADMIN_WORKSPACES_ENDPOINT = '/api/admin/workspaces';
export const ADMIN_STATS_ENDPOINT = '/api/admin/stats';
export const ADMIN_AUDIT_ENDPOINT = '/api/admin/audit';

/**
 * Typed HTTP client for every `/api/admin/*` capability endpoint (design
 * D109). Deliberately its own service, not a wrapper around
 * `WorkspaceService` — the admin area is a genuinely separate feature
 * area (design D110), and every response shape here is platform-admin
 * metadata-only (O1), never workspace-scoped content. `withCredentials`
 * matches every other data service in this app (design D8 — the session
 * lives in an httpOnly cookie).
 */
@Injectable({ providedIn: 'root' })
export class AdminService {
  private readonly http = inject(HttpClient);

  /** `GET /api/admin/users`. */
  listUsers(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>(ADMIN_USERS_ENDPOINT, { withCredentials: true });
  }

  /** `GET /api/admin/workspaces`. */
  listWorkspaces(): Observable<AdminWorkspace[]> {
    return this.http.get<AdminWorkspace[]>(ADMIN_WORKSPACES_ENDPOINT, { withCredentials: true });
  }

  /** `GET /api/admin/stats`. */
  getStats(): Observable<AdminStats> {
    return this.http.get<AdminStats>(ADMIN_STATS_ENDPOINT, { withCredentials: true });
  }

  /** `GET /api/admin/audit` — every row, platform-wide (design D105). */
  getAuditLog(): Observable<AdminAuditLogEntry[]> {
    return this.http.get<AdminAuditLogEntry[]>(ADMIN_AUDIT_ENDPOINT, { withCredentials: true });
  }

  /** `POST /api/admin/users/{id}/deactivate` -> 204. */
  deactivateUser(userId: string): Observable<void> {
    return this.http.post<void>(
      `${ADMIN_USERS_ENDPOINT}/${userId}/deactivate`,
      {},
      { withCredentials: true },
    );
  }

  /** `POST /api/admin/users/{id}/reactivate` -> 204. */
  reactivateUser(userId: string): Observable<void> {
    return this.http.post<void>(
      `${ADMIN_USERS_ENDPOINT}/${userId}/reactivate`,
      {},
      { withCredentials: true },
    );
  }

  /** `POST /api/admin/workspaces/{id}/deactivate` -> 204. */
  deactivateWorkspace(workspaceId: string): Observable<void> {
    return this.http.post<void>(
      `${ADMIN_WORKSPACES_ENDPOINT}/${workspaceId}/deactivate`,
      {},
      { withCredentials: true },
    );
  }

  /** `POST /api/admin/workspaces/{id}/reactivate` -> 204. */
  reactivateWorkspace(workspaceId: string): Observable<void> {
    return this.http.post<void>(
      `${ADMIN_WORKSPACES_ENDPOINT}/${workspaceId}/reactivate`,
      {},
      { withCredentials: true },
    );
  }

  /** `POST /api/admin/admins/{user_id}` -> 204 (grant). */
  grantAdmin(userId: string): Observable<void> {
    return this.http.post<void>(`/api/admin/admins/${userId}`, {}, { withCredentials: true });
  }

  /** `DELETE /api/admin/admins/{user_id}` -> 204 (revoke; self-revocation
   * allowed per design O6). */
  revokeAdmin(userId: string): Observable<void> {
    return this.http.delete<void>(`/api/admin/admins/${userId}`, { withCredentials: true });
  }
}
