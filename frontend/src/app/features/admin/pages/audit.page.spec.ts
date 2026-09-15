import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AdminAuditPage } from './audit.page';

const AUDIT_RESPONSE = [
  {
    id: 'audit-1',
    created_at: '2026-01-03T00:00:00Z',
    actor_user_id: 'admin-1',
    actor_was_platform_admin: true,
    action: 'platform.user_deactivated',
    target_type: 'user',
    target_id: 'user-1',
    workspace_id: null,
    metadata: {},
  },
  {
    id: 'audit-2',
    created_at: '2026-01-04T00:00:00Z',
    actor_user_id: 'owner-1',
    actor_was_platform_admin: false,
    action: 'workspace.renamed',
    target_type: 'workspace',
    target_id: 'ws-1',
    workspace_id: 'ws-1',
    metadata: {},
  },
];

const EN_LANG = {
  admin: {
    audit: {
      title: 'Platform audit log',
      loading: 'Loading…',
      loadError: 'Could not load the audit log.',
      empty: 'No audit events yet.',
    },
  },
};

describe('AdminAuditPage', () => {
  let fixture: ComponentFixture<AdminAuditPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        AdminAuditPage,
        TranslocoTestingModule.forRoot({
          langs: { en: EN_LANG },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AdminAuditPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('renders every entry from GET /api/admin/audit, platform-wide and unfiltered', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/audit').flush(AUDIT_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('platform.user_deactivated');
    expect(text).toContain('workspace.renamed');
  });

  it('renders the empty state when there are no audit entries', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/audit').flush([]);
    await fixture.whenStable();
    fixture.detectChanges();

    const empty = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="admin-audit-empty"]',
    );
    expect(empty).toBeTruthy();
  });

  it('shows a load error when the audit request fails', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/audit').flush('error', { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Could not load the audit log.');
  });
});
