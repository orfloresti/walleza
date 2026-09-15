/**
 * `AdminService` HTTP contract tests (Phase 8 Unit 7), same
 * `HttpTestingController` pattern as `WorkspaceService`'s own spec — no
 * live backend, proving each call hits the exact path/method the
 * backend's `app/admin/{router,schemas}.py` (Phase 8 Unit 3) defines.
 */

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AdminService } from './admin.service';

describe('AdminService', () => {
  let service: AdminService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AdminService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/admin/users lists users', async () => {
    const promise = firstValueFrom(service.listUsers());
    const req = httpMock.expectOne('/api/admin/users');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush([]);
    expect(await promise).toEqual([]);
  });

  it('GET /api/admin/workspaces lists workspaces', async () => {
    const promise = firstValueFrom(service.listWorkspaces());
    const req = httpMock.expectOne('/api/admin/workspaces');
    expect(req.request.method).toBe('GET');
    req.flush([]);
    expect(await promise).toEqual([]);
  });

  it('GET /api/admin/stats fetches aggregate stats', async () => {
    const stats = {
      total_users: 1,
      total_workspaces: 1,
      total_platform_admins: 1,
      deactivated_users: 0,
      deactivated_workspaces: 0,
    };
    const promise = firstValueFrom(service.getStats());
    const req = httpMock.expectOne('/api/admin/stats');
    expect(req.request.method).toBe('GET');
    req.flush(stats);
    expect(await promise).toEqual(stats);
  });

  it('GET /api/admin/audit fetches every entry, unfiltered', async () => {
    const promise = firstValueFrom(service.getAuditLog());
    const req = httpMock.expectOne('/api/admin/audit');
    expect(req.request.method).toBe('GET');
    req.flush([]);
    expect(await promise).toEqual([]);
  });

  it('POST /api/admin/users/{id}/deactivate deactivates a user', async () => {
    const promise = firstValueFrom(service.deactivateUser('user-1'));
    const req = httpMock.expectOne('/api/admin/users/user-1/deactivate');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });

  it('POST /api/admin/users/{id}/reactivate reactivates a user', async () => {
    const promise = firstValueFrom(service.reactivateUser('user-1'));
    const req = httpMock.expectOne('/api/admin/users/user-1/reactivate');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });

  it('POST /api/admin/workspaces/{id}/deactivate deactivates a workspace', async () => {
    const promise = firstValueFrom(service.deactivateWorkspace('ws-1'));
    const req = httpMock.expectOne('/api/admin/workspaces/ws-1/deactivate');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });

  it('POST /api/admin/workspaces/{id}/reactivate reactivates a workspace', async () => {
    const promise = firstValueFrom(service.reactivateWorkspace('ws-1'));
    const req = httpMock.expectOne('/api/admin/workspaces/ws-1/reactivate');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });

  it('POST /api/admin/admins/{user_id} grants platform-admin access', async () => {
    const promise = firstValueFrom(service.grantAdmin('user-1'));
    const req = httpMock.expectOne('/api/admin/admins/user-1');
    expect(req.request.method).toBe('POST');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });

  it('DELETE /api/admin/admins/{user_id} revokes platform-admin access', async () => {
    const promise = firstValueFrom(service.revokeAdmin('user-1'));
    const req = httpMock.expectOne('/api/admin/admins/user-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    await promise;
  });
});
