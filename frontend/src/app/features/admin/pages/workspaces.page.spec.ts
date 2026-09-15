import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AdminWorkspacesPage } from './workspaces.page';

const WORKSPACES_RESPONSE = [
  {
    id: 'ws-1',
    name: 'Solo',
    created_at: '2026-01-01T00:00:00Z',
    member_count: 1,
    is_active: true,
  },
  {
    id: 'ws-2',
    name: 'Team',
    created_at: '2026-01-02T00:00:00Z',
    member_count: 3,
    is_active: false,
  },
];

const EN_LANG = {
  admin: {
    workspaces: {
      title: 'Workspaces',
      loading: 'Loading…',
      loadError: 'Could not load workspaces.',
      empty: 'No workspaces yet.',
      deactivatedBadge: 'Deactivated',
      deactivate: 'Deactivate',
      reactivate: 'Reactivate',
      deactivateError: 'Could not deactivate that workspace.',
      reactivateError: 'Could not reactivate that workspace.',
    },
  },
};

describe('AdminWorkspacesPage', () => {
  let fixture: ComponentFixture<AdminWorkspacesPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        AdminWorkspacesPage,
        TranslocoTestingModule.forRoot({
          langs: { en: EN_LANG },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AdminWorkspacesPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('renders the workspaces list from GET /api/admin/workspaces', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/workspaces').flush(WORKSPACES_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Solo');
    expect(text).toContain('Team');
    expect(text).toContain('Deactivated');
  });

  it('reactivates a deactivated workspace and reloads the list', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/admin/workspaces').flush(WORKSPACES_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();

    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ) as HTMLButtonElement[];
    const reactivateButton = buttons.find((b) => b.textContent?.trim() === 'Reactivate');
    expect(reactivateButton).toBeTruthy();
    reactivateButton!.click();

    httpMock
      .expectOne('/api/admin/workspaces/ws-2/reactivate')
      .flush(null, { status: 204, statusText: 'No Content' });
    httpMock.expectOne('/api/admin/workspaces').flush(WORKSPACES_RESPONSE);
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('shows a load error when the workspaces request fails', async () => {
    fixture.detectChanges();
    httpMock
      .expectOne('/api/admin/workspaces')
      .flush('error', { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Could not load workspaces.');
  });
});
