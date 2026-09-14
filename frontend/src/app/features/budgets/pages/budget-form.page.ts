import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiFieldComponent,
  UiInputComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
  UiSelectComponent,
  type UiSelectOption,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import { BudgetCreate, BudgetUpdate, BudgetsService } from '../data/budgets.service';

/** Sentinel `ui-select` value for "no account / all accounts" (design
 * D72's category-only budget) — `''` is reserved for "nothing chosen yet"
 * by `ui-select`'s own empty-value convention (see `recurring-form.page.ts`'s
 * account select), so this sentinel must be a distinct, non-empty value. */
const NO_ACCOUNT_VALUE = '__none__';

/**
 * Create/edit budget form (Phase 5 PR2, task 2.4, design's Frontend Shape
 * section): category select (required), account select (optional, "no
 * account / all accounts" sentinel), amount, currency, optional name.
 *
 * Design D73: when an account is selected, the budget's `currency` MUST
 * equal that account's currency — selecting an account pre-fills and locks
 * the currency input rather than letting the user pick a mismatched value
 * that the server would reject with 422 anyway (least surprise). Choosing
 * "no account" unlocks the field again. The server remains the source of
 * truth for the rule (`service.create_budget`/`update_budget`); this is
 * purely a UX shortcut, not a client-side re-implementation of D73 — a
 * currency-mismatch 422 (e.g. a stale pre-filled value from switching
 * accounts) still surfaces verbatim via `ui-alert [message]`, same
 * convention as every other form in this codebase.
 *
 * A `:id` route param switches the form into edit mode, matching every
 * other feature's form page. Money/currency are kept as raw `string`
 * end-to-end (design D19).
 */
@Component({
  selector: 'app-budget-form-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiFieldComponent,
    UiInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-2xl px-4 py-6">
      <ui-page-header [titleKey]="isEditMode() ? 'budgets.editTitle' : 'budgets.createTitle'" />

      @if (loading()) {
        <ui-loading messageKey="budgets.loading" />
      } @else {
        <form (ngSubmit)="save()" class="flex flex-col gap-3">
          <ui-field labelKey="budgets.category">
            <ui-select
              name="categoryId"
              [required]="true"
              testId="budget-category-select"
              [options]="categoryOptions()"
              placeholderKey="budgets.selectCategory"
              [value]="categoryId()"
              (valueChange)="categoryId.set($event)"
            />
          </ui-field>

          <ui-field labelKey="budgets.account">
            <ui-select
              name="accountId"
              testId="budget-account-select"
              [options]="accountOptions()"
              [value]="accountSelectValue()"
              (valueChange)="setAccount($event)"
            />
          </ui-field>

          <ui-field labelKey="budgets.name">
            <ui-input name="name" testId="budget-name-input" [value]="name()" (valueChange)="name.set($event)" />
          </ui-field>

          <ui-field labelKey="budgets.amount">
            <ui-input
              name="amount"
              [required]="true"
              testId="budget-amount-input"
              [value]="amount()"
              (valueChange)="amount.set($event)"
            />
          </ui-field>

          <ui-field labelKey="budgets.currency">
            <ui-input
              name="currency"
              [required]="true"
              [disabled]="currencyLocked()"
              testId="budget-currency-input"
              [value]="currency()"
              (valueChange)="currency.set($event)"
            />
          </ui-field>

          <ui-button type="submit" variant="primary">
            {{ (isEditMode() ? 'budgets.save' : 'budgets.create') | transloco }}
          </ui-button>
        </form>
      }

      @if (errorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
      @if (serverErrorDetail(); as detail) {
        <ui-alert [message]="detail" testId="budget-server-error" />
      }
    </section>
  `,
})
export class BudgetFormPage {
  private readonly budgetsService = inject(BudgetsService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly transloco = inject(TranslocoService);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly categoryOptions = computed<UiSelectOption[]>(() =>
    this.categories().map((c) => ({ value: c.id, label: c.name })),
  );

  protected readonly accountOptions = computed<UiSelectOption[]>(() => [
    { value: NO_ACCOUNT_VALUE, label: this.transloco.translate('budgets.allAccounts') },
    ...this.accounts().map((a) => ({ value: a.id, label: a.name })),
  ]);

  protected readonly budgetId = signal<string | null>(null);
  protected readonly isEditMode = signal(false);
  protected readonly loading = signal(true);
  protected readonly errorKey = signal<string | null>(null);
  protected readonly serverErrorDetail = signal<string | null>(null);

  protected readonly categoryId = signal('');
  /** `null` means "no account / all accounts" (design D72). */
  protected readonly accountId = signal<string | null>(null);
  protected readonly name = signal('');
  protected readonly amount = signal('');
  protected readonly currency = signal('');

  protected readonly accountSelectValue = computed(() => this.accountId() ?? NO_ACCOUNT_VALUE);

  /** Design D73: the currency input locks whenever an account is selected
   * — its value is pre-filled from that account's own currency. */
  protected readonly currencyLocked = computed(() => this.accountId() !== null);

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.budgetId.set(id);
      this.isEditMode.set(true);
      this.loadExisting(id);
    } else {
      this.loading.set(false);
    }
  }

  protected setAccount(value: string): void {
    if (value === NO_ACCOUNT_VALUE || value === '') {
      this.accountId.set(null);
      return;
    }
    this.accountId.set(value);
    const account = this.accounts().find((a) => a.id === value);
    if (account) this.currency.set(account.currency);
  }

  private loadExisting(id: string): void {
    this.loading.set(true);
    this.budgetsService.getBudget(id).subscribe({
      next: (budget) => {
        this.categoryId.set(budget.category_id);
        this.accountId.set(budget.account_id);
        this.name.set(budget.name ?? '');
        this.amount.set(budget.amount);
        this.currency.set(budget.currency);
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.errorKey.set('budgets.loadError');
      },
    });
  }

  protected save(): void {
    this.errorKey.set(null);
    this.serverErrorDetail.set(null);

    const isEdit = this.isEditMode();
    const id = this.budgetId();
    const accountId = this.accountId();

    const request = isEdit && id
      ? this.budgetsService.updateBudget(id, {
          category_id: this.categoryId(),
          account_id: accountId,
          name: this.name() || null,
          amount: this.amount(),
          currency: this.currency(),
        } satisfies BudgetUpdate)
      : this.budgetsService.createBudget({
          category_id: this.categoryId(),
          account_id: accountId,
          name: this.name() || null,
          amount: this.amount(),
          currency: this.currency(),
        } satisfies BudgetCreate);

    request.subscribe({
      next: () => void this.router.navigateByUrl('/budgets'),
      error: (err: HttpErrorResponse) => {
        if (err.status === 422) {
          const detail = (err.error as { detail?: unknown } | null)?.detail;
          if (typeof detail === 'string') {
            this.serverErrorDetail.set(detail);
            return;
          }
          this.errorKey.set('budgets.saveError');
          return;
        }
        this.errorKey.set('budgets.saveError');
      },
    });
  }
}
