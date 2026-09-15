import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AdminUsersPage } from './users.page';

const USERS_RESPONSE = [
  {
    id: 'user-1',
    email: 'active@example.com',
    created_at: '2026-01-01T00:00:00Z',
    workspace_id: 'ws-1',
    workspace_name: 'Solo',
    is_platform_admin: false,
    is_deactivated: false,
  },
  {
    id: 'user-2',
    email: 'admin@example.com',
    created_at: '2026-01-02T00:00:00Z',
    workspace_id: 'ws-2',
    workspace_name: 'Team',
    is_platform_admin: true,
    is_deactivated: false,
  },
];

const EN_LANG = {
  admin: {
    users: {
      title: 'Users',
      loading: 'Loading…',
      loadError: 'Could not load users.',
      empty: 'No users yet.',
      deactivatedBadge: 'Deactivated',
      platformAdminBadge: 'Platform admin',
      deactivate: 'Deactivate',
      reactivate: 'Reactivate',
      grantAdmin: 'Grant admin',
      revokeAdmin: 'Revoke admin',
      deactivateError: 'Could not deactivate that user.',
      reactivateError: 'Could not reactivate that user.',
      grantAdminError: 'Could not grant platform-admin access.',
      revokeAdminError: 'Could not revoke platform-admin access.',
    },
  },
};

describe('AdminUsersPage', () => {
  let fixture: ComponentFixture<AdminUsersPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        AdminUsersPage,
        TranslocoTestingModule.forRoot({
          langs: { en: EN_LANG },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AdminUsersPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('renders the users list from GET /api/admin/users', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/users').flush(USERS_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('active@example.com');
    expect(text).toContain('admin@example.com');
    expect(text).toContain('Platform admin');
  });

  it('deactivates a user and reloads the list', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/users').flush(USERS_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ) as HTMLButtonElement[];
    const deactivateButton = buttons.find((b) => b.textContent?.trim() === 'Deactivate');
    expect(deactivateButton).toBeTruthy();
    deactivateButton!.click();

    httpMock
      .expectOne('/api/admin/users/user-1/deactivate')
      .flush(null, { status: 204, statusText: 'No Content' });
    httpMock.expectOne('/api/admin/users').flush(USERS_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('shows a load error when the users request fails', async () => {
    fixture.detectChanges();
    httpMock
      .expectOne('/api/admin/users')
      .flush('error', { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Could not load users.');
  });
});
