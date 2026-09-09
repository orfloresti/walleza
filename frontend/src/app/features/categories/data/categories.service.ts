import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

/** `type` enum excludes `transfer` (design decision 8 / D29 — categories
 * mirror the transaction type enum exactly). */
export type CategoryType = 'income' | 'expense';

/** `GET/POST/GET-by-id/PATCH /api/categories` response shape (design's
 * Interfaces/Contracts section). Flat list — the client groups by
 * `parent_id` into a two-level tree (design D29: exactly two levels). */
export interface Category {
  id: string;
  workspace_id: string;
  parent_id: string | null;
  name: string;
  icon: string | null;
  type: CategoryType;
  created_at: string;
  updated_at: string;
}

/** `POST /api/categories` request body (`CategoryCreateIn`). `parent_id`
 * omitted (or `null`) creates a top-level category; when present, the
 * referenced category must already be top-level itself (D29), enforced
 * server-side. */
export interface CategoryCreate {
  name: string;
  icon?: string | null;
  type: CategoryType;
  parent_id?: string | null;
}

/** `PATCH /api/categories/{id}` request body (`CategoryUpdateIn`) — every
 * field optional; only fields present are applied server-side
 * (`exclude_unset=True`). */
export interface CategoryUpdate {
  name?: string;
  icon?: string | null;
  type?: CategoryType;
  parent_id?: string | null;
}

export const CATEGORIES_ENDPOINT = '/api/categories';

/**
 * HTTP calls for the `category-management` capability (design's
 * Interfaces/Contracts table), mirroring `AccountsService`'s style: a
 * `signal`-based cache of the last-fetched list, `withCredentials` on
 * every call (design D8).
 *
 * The server already scopes every response to the caller's own workspace
 * (`visible_categories(scope)`) — this service and its consumers never
 * re-filter or re-derive visibility client-side, they only render what
 * the API returned.
 */
@Injectable({ providedIn: 'root' })
export class CategoriesService {
  private readonly http = inject(HttpClient);

  private readonly categoriesSignal = signal<Category[]>([]);
  readonly categories = this.categoriesSignal.asReadonly();

  /** `GET /api/categories` — flat list, visible in the caller's workspace. */
  listCategories(): Observable<Category[]> {
    return this.http
      .get<Category[]>(CATEGORIES_ENDPOINT, { withCredentials: true })
      .pipe(tap((categories) => this.categoriesSignal.set(categories)));
  }

  /** `POST /api/categories` — creates a top-level or child category. */
  createCategory(body: CategoryCreate): Observable<Category> {
    return this.http.post<Category>(CATEGORIES_ENDPOINT, body, { withCredentials: true });
  }

  /** `GET /api/categories/{id}` — 404 for a category outside the
   * caller's workspace (design D18: a 403 would confirm the row exists). */
  getCategory(id: string): Observable<Category> {
    return this.http.get<Category>(`${CATEGORIES_ENDPOINT}/${id}`, { withCredentials: true });
  }

  /** `PATCH /api/categories/{id}` — the one mutation path for
   * name/icon/type/parent_id. */
  updateCategory(id: string, changes: CategoryUpdate): Observable<Category> {
    return this.http.patch<Category>(`${CATEGORIES_ENDPOINT}/${id}`, changes, {
      withCredentials: true,
    });
  }

  /** `DELETE /api/categories/{id}` — 409 while it has children or is
   * referenced by a split line (design D28: no cascade, no silent
   * orphaning). */
  deleteCategory(id: string): Observable<void> {
    return this.http.delete<void>(`${CATEGORIES_ENDPOINT}/${id}`, { withCredentials: true });
  }
}
