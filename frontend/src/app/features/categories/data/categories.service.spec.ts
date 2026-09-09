/**
 * `CategoriesService` HTTP contract tests (Phase 2 PR6, task 7.5), same
 * `HttpTestingController` pattern `accounts.service.spec.ts` established
 * in Phase 1 — no live backend, only the real `HttpClient` against a mock
 * backend, proving each call hits the exact path/method/body
 * `app/categories/{router,schemas}.py` defines.
 */

import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { CategoriesService } from './categories.service';

const PARENT_CATEGORY_RESPONSE = {
  id: 'cat-1',
  workspace_id: 'ws-1',
  parent_id: null,
  name: 'Food',
  icon: '🍔',
  type: 'expense',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const CHILD_CATEGORY_RESPONSE = {
  ...PARENT_CATEGORY_RESPONSE,
  id: 'cat-2',
  parent_id: 'cat-1',
  name: 'Groceries',
  icon: '🛒',
};

describe('CategoriesService', () => {
  let service: CategoriesService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(CategoriesService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('GET /api/categories lists the flat category set and caches it in the signal', async () => {
    const promise = firstValueFrom(service.listCategories());

    const req = httpMock.expectOne('/api/categories');
    expect(req.request.method).toBe('GET');
    expect(req.request.withCredentials).toBe(true);
    req.flush([PARENT_CATEGORY_RESPONSE, CHILD_CATEGORY_RESPONSE]);

    const categories = await promise;
    expect(categories).toEqual([PARENT_CATEGORY_RESPONSE, CHILD_CATEGORY_RESPONSE]);
    expect(service.categories()).toEqual([PARENT_CATEGORY_RESPONSE, CHILD_CATEGORY_RESPONSE]);
  });

  it('POST /api/categories creates a top-level category with the exact body shape (task focus)', async () => {
    const promise = firstValueFrom(
      service.createCategory({
        name: 'Food',
        icon: '🍔',
        type: 'expense',
        parent_id: null,
      }),
    );

    const req = httpMock.expectOne('/api/categories');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      name: 'Food',
      icon: '🍔',
      type: 'expense',
      parent_id: null,
    });
    req.flush(PARENT_CATEGORY_RESPONSE);

    const category = await promise;
    expect(category.name).toBe('Food');
  });

  it('POST /api/categories creates a child category referencing an existing parent_id', async () => {
    const promise = firstValueFrom(
      service.createCategory({
        name: 'Groceries',
        icon: '🛒',
        type: 'expense',
        parent_id: 'cat-1',
      }),
    );

    const req = httpMock.expectOne('/api/categories');
    expect(req.request.body).toEqual({
      name: 'Groceries',
      icon: '🛒',
      type: 'expense',
      parent_id: 'cat-1',
    });
    req.flush(CHILD_CATEGORY_RESPONSE);

    const category = await promise;
    expect(category.parent_id).toBe('cat-1');
  });

  it('GET /api/categories/{id} fetches a single category', async () => {
    const promise = firstValueFrom(service.getCategory('cat-1'));

    const req = httpMock.expectOne('/api/categories/cat-1');
    expect(req.request.method).toBe('GET');
    req.flush(PARENT_CATEGORY_RESPONSE);

    const category = await promise;
    expect(category.id).toBe('cat-1');
  });

  it('PATCH /api/categories/{id} updates category fields', async () => {
    const promise = firstValueFrom(service.updateCategory('cat-1', { name: 'Groceries' }));

    const req = httpMock.expectOne('/api/categories/cat-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ name: 'Groceries' });
    req.flush({ ...PARENT_CATEGORY_RESPONSE, name: 'Groceries' });

    const category = await promise;
    expect(category.name).toBe('Groceries');
  });

  it('DELETE /api/categories/{id} deletes a category', async () => {
    const promise = firstValueFrom(service.deleteCategory('cat-1'));

    const req = httpMock.expectOne('/api/categories/cat-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });

    await promise;
  });
});
