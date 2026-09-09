/**
 * `CategoriesListPage` — Phase 2 PR6 (task 7.1): renders `GET
 * /api/categories` grouped into a parent/child tree, creates a category,
 * and deletes one. Real `HttpClient` against `HttpTestingController`, no
 * live backend — same pattern as `accounts-list.page.spec.ts`.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CategoriesListPage } from './categories-list.page';

const PARENT_CATEGORY = {
  id: 'cat-1',
  workspace_id: 'ws-1',
  parent_id: null,
  name: 'Food',
  icon: '🍔',
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const CHILD_CATEGORY = {
  ...PARENT_CATEGORY,
  id: 'cat-2',
  parent_id: 'cat-1',
  name: 'Groceries',
  icon: '🛒',
};

describe('CategoriesListPage', () => {
  let fixture: ComponentFixture<CategoriesListPage>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        CategoriesListPage,
        TranslocoTestingModule.forRoot({
          langs: {
            en: {
              categories: {
                title: 'Categories',
                loading: 'Loading…',
                loadError: 'Could not load your categories.',
                delete: 'Delete',
                deleteError: 'Could not delete that category.',
                deleteBlocked: 'This category has children or is in use and cannot be deleted.',
                createTitle: 'Add category',
                name: 'Name',
                icon: 'Icon',
                type: 'Type',
                income: 'Income',
                expense: 'Expense',
                parent: 'Parent category',
                noParent: 'None (top-level)',
                create: 'Create',
                createError: 'Could not create that category.',
              },
            },
          },
          translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CategoriesListPage);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('renders the hierarchy: a child nested under its parent (task focus)', async () => {
    fixture.detectChanges();

    const req = httpMock.expectOne('/api/categories');
    req.flush([PARENT_CATEGORY, CHILD_CATEGORY]);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const text = el.textContent ?? '';
    expect(text).toContain('Food');
    expect(text).toContain('Groceries');

    const childList = el.querySelector('[data-testid="category-children"]');
    expect(childList).toBeTruthy();
    expect(childList?.textContent).toContain('Groceries');
  });

  it('does not render a top-level category as its own child group', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/categories').flush([PARENT_CATEGORY]);
    await fixture.whenStable();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('[data-testid="category-children"]')).toBeFalsy();
  });

  it('submitting the create form calls POST /api/categories with the exact body shape (task focus)', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/categories').flush([PARENT_CATEGORY]);
    await fixture.whenStable();
    fixture.detectChanges();

    const component = fixture.componentInstance;
    component['name'].set('Transport');
    component['icon'].set('🚌');
    component['type'].set('expense');
    component['parentId'].set('cat-1');
    fixture.detectChanges();

    const form = (fixture.nativeElement as HTMLElement).querySelector('form') as HTMLFormElement;
    form.dispatchEvent(new Event('submit'));

    const req = httpMock.expectOne('/api/categories');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Transport',
      icon: '🚌',
      type: 'expense',
      parent_id: 'cat-1',
    });
    req.flush({ ...CHILD_CATEGORY, name: 'Transport', icon: '🚌', id: 'cat-3' });

    // createCategory() reloads the list afterwards.
    httpMock.expectOne('/api/categories').flush([]);
    await fixture.whenStable();
  });

  it('clicking delete calls DELETE /api/categories/{id}', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/categories').flush([PARENT_CATEGORY]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    expect(deleteButton).toBeTruthy();
    deleteButton?.click();

    const req = httpMock.expectOne('/api/categories/cat-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    // deleteCategory() reloads the list afterwards.
    httpMock.expectOne('/api/categories').flush([]);
    await fixture.whenStable();
  });

  it('shows a blocked-deletion message on a 409 response (design D28)', async () => {
    fixture.detectChanges();
    httpMock.expectOne('/api/categories').flush([PARENT_CATEGORY]);
    await fixture.whenStable();
    fixture.detectChanges();

    const deleteButton = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ).find((btn) => btn.textContent?.includes('Delete'));
    deleteButton?.click();

    const req = httpMock.expectOne('/api/categories/cat-1');
    req.flush({ detail: 'blocked' }, { status: 409, statusText: 'Conflict' });
    await fixture.whenStable();
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('children or is in use');
  });
});
