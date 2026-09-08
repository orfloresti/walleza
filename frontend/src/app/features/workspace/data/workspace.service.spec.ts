/**
 * `WorkspaceService` HTTP contract tests (Phase 1 PR4, task 7.2), same
 * `HttpTestingController` pattern `auth.guard.spec.ts` established in
 * Phase 0 — no live backend, only the real `HttpClient` against a mock
 * backend, proving each call hits the exact path/method/body the
 * backend's `app/workspace/{router,schemas}.py` (Phase 1 PR2) defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { WorkspaceService } from './workspace.service';

describe('WorkspaceService', () => {
  let service: WorkspaceService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(WorkspaceService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/workspace resolves the get-or-create workspace and caches it in the signal', async () => {
    const promise = firstValueFrom(service.getWorkspace());

    const req = httpMock.expectOne('/api/workspace');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush({
      id: 'ws-1',
      name: "user@example.com's workspace",
      members: [{ user_id: 'user-1', email: 'user@example.com', joined_at: '2026-01-01T00:00:00Z' }],
    });

    const workspace = await promise;
    expect(workspace.id).toBe('ws-1');
    expect(service.workspace()).toEqual(workspace);
  });

  it('POST /api/workspace/invites creates a shareable invite link', async () => {
    const promise = firstValueFrom(service.createInvite());

    const req = httpMock.expectOne('/api/workspace/invites');
    expect(req.request.method).toBe('POST');
    expect(req.request.withCredentials).toBe(true);
    req.flush({ id: 'inv-1', url: '/join/rawtoken123', expires_at: '2026-01-08T00:00:00Z' });

    const invite = await promise;
    expect(invite.url).toBe('/join/rawtoken123');
  });

  it('POST /api/workspace/invites/accept sends the token in the request body', async () => {
    const promise = firstValueFrom(service.acceptInvite('rawtoken123'));

    const req = httpMock.expectOne('/api/workspace/invites/accept');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: 'rawtoken123' });
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });

  it('DELETE /api/workspace/members/{userId} calls the exact member-removal endpoint (task focus)', async () => {
    const promise = firstValueFrom(service.removeMember('user-2'));

    const req = httpMock.expectOne('/api/workspace/members/user-2');
    expect(req.request.method).toBe('DELETE');
    expect(req.request.withCredentials).toBe(true);
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });
});
