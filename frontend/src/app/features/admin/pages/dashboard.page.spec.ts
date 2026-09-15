import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AdminDashboardPage } from './dashboard.page';

const STATS_RESPONSE = {
  total_users: 5,
  total_workspaces: 3,
  total_platform_admins: 1,
  deactivated_users: 1,
  deactivated_workspaces: 0,
};

describe('AdminDashboardPage', () => {
  let fixture: ComponentFixture<AdminDashboardPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        AdminDashboardPage,
        TranslocoTestingModule.forRoot({
          langs: {
            en: {
              admin: {
                nav: { users: 'Users', workspaces: 'Workspaces', audit: 'Audit log' },
                dashboard: {
                  title: 'Admin overview',
                  loading: 'Loading…',
                  loadError: 'Could not load platform stats.',
                  totalUsers: 'Total users',
                  totalWorkspaces: 'Total workspaces',
                  totalPlatformAdmins: 'Platform admins',
                  deactivatedUsers: 'Deactivated users',
                  deactivatedWorkspaces: 'Deactivated workspaces',
                },
              },
            },
          },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AdminDashboardPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('renders aggregate stats from GET /api/admin/stats', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/stats').flush(STATS_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('5');
    expect(text).toContain('3');
    expect(text).toContain('1');
  });

  it('shows a load error when the stats request fails', async () => {
    fixture.detectChanges();
    httpMock
      .expectOne('/api/admin/stats')
      .flush('error', { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Could not load platform stats.');
  });
});
