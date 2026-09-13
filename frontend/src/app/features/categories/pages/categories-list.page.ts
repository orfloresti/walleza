import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiInputComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  UiSelectOption,
} from '../../../shared/ui';
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
 *
 * Phase UI (PR6) — migrated to the `shared/ui/` kit. The parent-category
 * dropdown becomes `ui-select`, which owns its own `<option>` elements
 * (design D57) — `parentOptions` is the `computed()` mapping from
 * top-level categories to `UiSelectOption[]` this requires; the
 * `category-children` testid is preserved on the nested `ui-list`
 * (forwarded onto its native `<ul>`, D58). The `category-type` select
 * stays a plain native `<select>`: its two options ("Expense"/"Income")
 * are translated labels, and `ui-select` renders `option.label` as plain
 * text (no `transloco` pipe) — out of scope for this migration, and no
 * spec queries it by testid, so this is a deliberate, documented
 * judgment call rather than a silent gap.
 */
@Component({
  selector: 'app-categories-list-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiInputComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-4xl px-4 py-6">
      <ui-page-header titleKey="categories.title" />

      @if (loading()) {
        <ui-loading messageKey="categories.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="categories.loadError" />
      } @else if (groups().length === 0) {
        <ui-empty-state
          testId="categories-empty"
          titleKey="categories.empty.title"
          messageKey="categories.empty.body"
        />
      } @else {
        <ui-list testId="categories-list">
          @for (group of groups(); track group.parent.id) {
            <ui-list-row>
              <ui-list-cell labelKey="categories.name">
                <span>{{ group.parent.icon }} {{ group.parent.name }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="categories.type">
                <span data-testid="category-type">{{ group.parent.type }}</span>
              </ui-list-cell>
              <ui-list-cell class="md:ml-auto">
                <ui-button variant="danger" size="sm" (click)="deleteCategory(group.parent.id)">
                  {{ 'categories.delete' | transloco }}
                </ui-button>
              </ui-list-cell>
              @if (group.children.length > 0) {
                <ui-list testId="category-children">
                  @for (child of group.children; track child.id) {
                    <ui-list-row>
                      <ui-list-cell labelKey="categories.name">
                        <span>{{ child.icon }} {{ child.name }}</span>
                      </ui-list-cell>
                      <ui-list-cell labelKey="categories.type">
                        <span data-testid="category-type">{{ child.type }}</span>
                      </ui-list-cell>
                      <ui-list-cell class="md:ml-auto">
                        <ui-button variant="danger" size="sm" (click)="deleteCategory(child.id)">
                          {{ 'categories.delete' | transloco }}
                        </ui-button>
                      </ui-list-cell>
                    </ui-list-row>
                  }
                </ui-list>
              }
            </ui-list-row>
          }
        </ui-list>
      }

      <ui-card>
        <form (ngSubmit)="createCategory()" class="flex flex-col gap-3">
          <h2 class="text-lg font-semibold text-on-surface">
            {{ 'categories.createTitle' | transloco }}
          </h2>

          <ui-field labelKey="categories.name">
            <ui-input name="name" [required]="true" [(value)]="name" />
          </ui-field>

          <ui-field labelKey="categories.icon">
            <ui-input name="icon" [(value)]="icon" />
          </ui-field>

          <ui-field labelKey="categories.type">
            <select
              name="type"
              data-testid="category-type-select"
              [ngModel]="type()"
              (ngModelChange)="type.set($event)"
            >
              <option value="expense">{{ 'categories.expense' | transloco }}</option>
              <option value="income">{{ 'categories.income' | transloco }}</option>
            </select>
          </ui-field>

          <ui-field labelKey="categories.parent">
            <ui-select
              name="parentId"
              testId="category-parent-select"
              [options]="parentOptions()"
              placeholderKey="categories.noParent"
              [(value)]="parentId"
            />
          </ui-field>

          <ui-button type="submit" variant="primary">{{ 'categories.create' | transloco }}</ui-button>
        </form>
      </ui-card>

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" />
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

  /** Top-level categories, mapped to `UiSelectOption[]` for `ui-select`
   * (design D57 — the component owns its own `<option>` elements rather
   * than projecting page-authored ones). A child cannot itself be
   * selected as a parent (design D29: exactly two hierarchy levels). */
  protected readonly parentOptions = computed<UiSelectOption[]>(() =>
    this.categories()
      .filter((category) => category.parent_id === null)
      .map((category) => ({ value: category.id, label: category.name })),
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
