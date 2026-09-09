import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { TranslocoPipe } from '@jsverse/transloco';

import { Category, CategoriesService, CategoryType } from '../data/categories.service';

/** One top-level category paired with its (at most one level deep, per
 * design D29) children — a purely client-side grouping of the flat
 * `GET /api/categories` response, never re-derived visibility. */
interface CategoryGroup {
  parent: Category;
  children: Category[];
}

/**
 * Categories list/CRUD view (Phase 2 PR6, task 7.1): renders
 * `GET /api/categories` grouped into a two-level parent/child tree
 * (design D29), a create form covering name/icon/type/parent_id (a
 * dropdown restricted to existing top-level categories, since a child
 * cannot itself be a parent), and a delete action per row. Deliberately
 * unpolished per the proposal: functionally correct, not styled, same
 * minimalism as `features/accounts/accounts-list.page.ts`.
 *
 * Workspace-scoped access (design D14/D18) is enforced entirely
 * server-side by `visible_categories(scope)` — this page never filters
 * or re-derives visibility client-side, it only renders what
 * `GET /api/categories` returns.
 */
@Component({
  selector: 'app-categories-list-page',
  imports: [FormsModule, TranslocoPipe],
  template: `
    <section>
      <h1>{{ 'categories.title' | transloco }}</h1>

      @if (loading()) {
        <p>{{ 'categories.loading' | transloco }}</p>
      } @else if (loadError()) {
        <p role="alert">{{ 'categories.loadError' | transloco }}</p>
      } @else {
        <ul data-testid="categories-list">
          @for (group of groups(); track group.parent.id) {
            <li>
              <span>{{ group.parent.icon }} {{ group.parent.name }}</span>
              <span data-testid="category-type">{{ group.parent.type }}</span>
              <button type="button" (click)="deleteCategory(group.parent.id)">
                {{ 'categories.delete' | transloco }}
              </button>
              @if (group.children.length > 0) {
                <ul data-testid="category-children">
                  @for (child of group.children; track child.id) {
                    <li>
                      <span>{{ child.icon }} {{ child.name }}</span>
                      <span data-testid="category-type">{{ child.type }}</span>
                      <button type="button" (click)="deleteCategory(child.id)">
                        {{ 'categories.delete' | transloco }}
                      </button>
                    </li>
                  }
                </ul>
              }
            </li>
          }
        </ul>
      }

      <form (ngSubmit)="createCategory()">
        <h2>{{ 'categories.createTitle' | transloco }}</h2>

        <label>
          {{ 'categories.name' | transloco }}
          <input
            type="text"
            name="name"
            required
            [ngModel]="name()"
            (ngModelChange)="name.set($event)"
          />
        </label>

        <label>
          {{ 'categories.icon' | transloco }}
          <input
            type="text"
            name="icon"
            [ngModel]="icon()"
            (ngModelChange)="icon.set($event)"
          />
        </label>

        <label>
          {{ 'categories.type' | transloco }}
          <select
            name="type"
            data-testid="category-type-select"
            [ngModel]="type()"
            (ngModelChange)="type.set($event)"
          >
            <option value="expense">{{ 'categories.expense' | transloco }}</option>
            <option value="income">{{ 'categories.income' | transloco }}</option>
          </select>
        </label>

        <label>
          {{ 'categories.parent' | transloco }}
          <select
            name="parentId"
            data-testid="category-parent-select"
            [ngModel]="parentId()"
            (ngModelChange)="parentId.set($event)"
          >
            <option value="">{{ 'categories.noParent' | transloco }}</option>
            @for (topLevel of topLevelCategories(); track topLevel.id) {
              <option [value]="topLevel.id">{{ topLevel.name }}</option>
            }
          </select>
        </label>

        <button type="submit">{{ 'categories.create' | transloco }}</button>
      </form>

      @if (actionErrorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
    </section>
  `,
})
export class CategoriesListPage {
  private readonly categoriesService = inject(CategoriesService);

  protected readonly categories = this.categoriesService.categories;
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly name = signal('');
  protected readonly icon = signal('');
  protected readonly type = signal<CategoryType>('expense');
  protected readonly parentId = signal('');

  /** Top-level categories only — a child cannot itself be selected as a
   * parent (design D29: exactly two hierarchy levels). */
  protected readonly topLevelCategories = computed(() =>
    this.categories().filter((category) => category.parent_id === null),
  );

  /** Groups the flat list into parent/children pairs for rendering
   * (design D29's exactly-two-levels invariant means every category is
   * either a group's `parent` or exactly one group's `child`, never
   * both). */
  protected readonly groups = computed<CategoryGroup[]>(() => {
    const all = this.categories();
    const parents = all.filter((category) => category.parent_id === null);
    return parents.map((parent) => ({
      parent,
      children: all.filter((category) => category.parent_id === parent.id),
    }));
  });

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.categoriesService.listCategories().subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected createCategory(): void {
    this.actionErrorKey.set(null);
    this.categoriesService
      .createCategory({
        name: this.name(),
        icon: this.icon() || null,
        type: this.type(),
        parent_id: this.parentId() || null,
      })
      .subscribe({
        next: () => {
          this.name.set('');
          this.icon.set('');
          this.type.set('expense');
          this.parentId.set('');
          this.load();
        },
        error: () => this.actionErrorKey.set('categories.createError'),
      });
  }

  protected deleteCategory(id: string): void {
    this.actionErrorKey.set(null);
    this.categoriesService.deleteCategory(id).subscribe({
      next: () => this.load(),
      error: (err: HttpErrorResponse) => {
        // Design D28: 409 while the category has children or is
        // referenced by a split line — no cascade, no silent orphaning.
        this.actionErrorKey.set(
          err.status === 409 ? 'categories.deleteBlocked' : 'categories.deleteError',
        );
      },
    });
  }
}
