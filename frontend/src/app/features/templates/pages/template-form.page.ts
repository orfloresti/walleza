import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { AccountsService } from '../../accounts/data/accounts.service';
import { CategoriesService } from '../../categories/data/categories.service';
import {
  SplitAllocationRowsComponent,
  SplitRowValue,
} from '../../transactions/ui/split-allocation-rows/split-allocation-rows.component';
import {
  parseSplitMismatchError,
  SplitMismatchError,
} from '../../transactions/ui/split-allocation-rows/split-mismatch-error';
import { TemplateCreate, TemplateType, TemplateUpdate, TemplatesService } from '../data/templates.service';

/**
 * Create/edit template form (Phase 4 PR5, task 5.1): name, account,
 * type, amount, notes, position, and an inline split-allocation editor
 * reused verbatim from `features/transactions/ui/split-allocation-rows`
 * (design D55's template split table mirrors `transaction_category_split`
 * exactly, so the same generic category+amount row editor and the same
 * server-authoritative mismatch parsing apply unchanged).
 *
 * A `:id` route param switches the form into edit mode
 * (`templates.routes.ts`'s `:id/edit` route); its absence (the `new`
 * route) means create mode. Money is kept as a raw `string` end-to-end
 * (design D19) — never parsed into a JS number.
 *
 * A 422 on save is inspected for a split-sum mismatch (same message
 * shape `app.templates.service.replace_template_splits` produces,
 * mirroring `app.transactions.service.replace_splits`) and routed to the
 * split editor's own `mismatchError` input; any other 422 renders its
 * `detail` verbatim (task 5.5's "verbatim 422 error rendering"
 * requirement).
 */
@Component({
  selector: 'app-template-form-page',
  imports: [FormsModule, TranslocoPipe, SplitAllocationRowsComponent],
  template: `
    <section>
      <h1>{{ (isEditMode() ? 'templates.editTitle' : 'templates.createTitle') | transloco }}</h1>

      @if (loading()) {
        <p>{{ 'templates.loading' | transloco }}</p>
      } @else {
        <form (ngSubmit)="save()">
          <label>
            {{ 'templates.name' | transloco }}
            <input
              type="text"
              name="name"
              required
              data-testid="template-name-input"
              [ngModel]="name()"
              (ngModelChange)="name.set($event)"
            />
          </label>

          <label>
            {{ 'templates.account' | transloco }}
            <select
              name="accountId"
              required
              data-testid="template-account-select"
              [ngModel]="accountId()"
              (ngModelChange)="accountId.set($event)"
            >
              <option value="">{{ 'templates.selectAccount' | transloco }}</option>
              @for (account of accounts(); track account.id) {
                <option [value]="account.id">{{ account.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'templates.type' | transloco }}
            <select
              name="type"
              data-testid="template-type-select"
              [ngModel]="type()"
              (ngModelChange)="type.set($event)"
            >
              <option value="expense">{{ 'templates.expense' | transloco }}</option>
              <option value="income">{{ 'templates.income' | transloco }}</option>
            </select>
          </label>

          <label>
            {{ 'templates.amount' | transloco }}
            <input
              type="text"
              name="amount"
              required
              data-testid="template-amount-input"
              [ngModel]="amount()"
              (ngModelChange)="amount.set($event)"
            />
          </label>

          <label>
            {{ 'templates.notes' | transloco }}
            <input
              type="text"
              name="notes"
              [ngModel]="notes()"
              (ngModelChange)="notes.set($event)"
            />
          </label>

          <label>
            {{ 'templates.position' | transloco }}
            <input
              type="number"
              name="position"
              [ngModel]="position()"
              (ngModelChange)="position.set($event)"
            />
          </label>

          <app-split-allocation-rows
            [categories]="categories()"
            [(rows)]="splitRows"
            [mismatchError]="splitMismatchError()"
          />

          <button type="submit">
            {{ (isEditMode() ? 'templates.save' : 'templates.create') | transloco }}
          </button>
        </form>
      }

      @if (errorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
      @if (serverErrorDetail(); as detail) {
        <p role="alert" data-testid="template-server-error">{{ detail }}</p>
      }
    </section>
  `,
})
export class TemplateFormPage {
  private readonly templatesService = inject(TemplatesService);
  private readonly accountsService = inject(AccountsService);
  private readonly categoriesService = inject(CategoriesService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly templateId = signal<string | null>(null);
  protected readonly isEditMode = signal(false);
  protected readonly loading = signal(true);
  protected readonly errorKey = signal<string | null>(null);
  /** The server's 422 `detail` rendered VERBATIM — never routed through
   * `transloco`, mirroring `transfer-form.page.ts`/`transaction-form.
   * page.ts`'s own precedent. */
  protected readonly serverErrorDetail = signal<string | null>(null);

  protected readonly name = signal('');
  protected readonly accountId = signal('');
  protected readonly type = signal<TemplateType>('expense');
  protected readonly amount = signal('');
  protected readonly notes = signal('');
  protected readonly position = signal(0);

  protected readonly splitRows = signal<SplitRowValue[]>([]);
  protected readonly splitMismatchError = signal<SplitMismatchError | null>(null);

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.templateId.set(id);
      this.isEditMode.set(true);
      this.loadExisting(id);
    } else {
      this.loading.set(false);
    }
  }

  private loadExisting(id: string): void {
    this.loading.set(true);
    this.templatesService.getTemplate(id).subscribe({
      next: (template) => {
        this.name.set(template.name);
        this.accountId.set(template.account_id);
        this.type.set(template.type);
        this.amount.set(template.amount);
        this.notes.set(template.notes ?? '');
        this.position.set(template.position);
        this.splitRows.set(
          template.splits.map((split) => ({ category_id: split.category_id, amount: split.amount })),
        );
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.errorKey.set('templates.loadError');
      },
    });
  }

  protected save(): void {
    this.errorKey.set(null);
    this.serverErrorDetail.set(null);
    this.splitMismatchError.set(null);

    const body: TemplateCreate | TemplateUpdate = {
      name: this.name(),
      account_id: this.accountId(),
      type: this.type(),
      amount: this.amount(),
      notes: this.notes() || null,
      position: this.position(),
    };

    const rows = this.splitRows();
    if (rows.length > 0) {
      body.splits = rows.map((row) => ({ category_id: row.category_id, amount: row.amount }));
    }

    const id = this.templateId();
    const request =
      this.isEditMode() && id
        ? this.templatesService.updateTemplate(id, body)
        : this.templatesService.createTemplate(body as TemplateCreate);

    request.subscribe({
      next: () => void this.router.navigateByUrl('/templates'),
      error: (err: HttpErrorResponse) => {
        if (err.status === 422) {
          const detail = (err.error as { detail?: unknown } | null)?.detail;
          const mismatch = parseSplitMismatchError(detail);
          if (mismatch) {
            this.splitMismatchError.set(mismatch);
            return;
          }
          if (typeof detail === 'string') {
            this.serverErrorDetail.set(detail);
            return;
          }
          this.errorKey.set('templates.saveError');
          return;
        }
        this.errorKey.set('templates.saveError');
      },
    });
  }
}
