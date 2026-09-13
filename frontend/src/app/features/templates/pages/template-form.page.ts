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
 * Create/edit template form (Phase 4 PR5, task 5.1; migrated to the
 * shared/ui kit in Phase 11 PR9, task 11.1): name, account, type, amount,
 * notes, position, and an inline split-allocation editor reused verbatim
 * from `features/transactions/ui/split-allocation-rows` (design D55's
 * template split table mirrors `transaction_category_split` exactly, so
 * the same generic category+amount row editor and the same
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
 * `detail` verbatim through `ui-alert`'s `[message]` branch (D59) —
 * never `| transloco`.
 */
@Component({
  selector: 'app-template-form-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    SplitAllocationRowsComponent,
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
      <ui-page-header
        [titleKey]="isEditMode() ? 'templates.editTitle' : 'templates.createTitle'"
      />

      @if (loading()) {
        <ui-loading messageKey="templates.loading" />
      } @else {
        <form (ngSubmit)="save()" class="flex flex-col gap-3">
          <ui-field labelKey="templates.name">
            <ui-input
              name="name"
              [required]="true"
              testId="template-name-input"
              [value]="name()"
              (valueChange)="name.set($event)"
            />
          </ui-field>

          <ui-field labelKey="templates.account">
            <ui-select
              name="accountId"
              [required]="true"
              testId="template-account-select"
              [options]="accountOptions()"
              placeholderKey="templates.selectAccount"
              [value]="accountId()"
              (valueChange)="accountId.set($event)"
            />
          </ui-field>

          <ui-field labelKey="templates.type">
            <ui-select
              name="type"
              testId="template-type-select"
              [options]="typeOptions()"
              [value]="type()"
              (valueChange)="setType($event)"
            />
          </ui-field>

          <ui-field labelKey="templates.amount">
            <ui-input
              name="amount"
              [required]="true"
              testId="template-amount-input"
              [value]="amount()"
              (valueChange)="amount.set($event)"
            />
          </ui-field>

          <ui-field labelKey="templates.notes">
            <ui-input name="notes" [value]="notes()" (valueChange)="notes.set($event)" />
          </ui-field>

          <ui-field labelKey="templates.position">
            <ui-input
              type="number"
              name="position"
              [value]="position().toString()"
              (valueChange)="setPosition($event)"
            />
          </ui-field>

          <app-split-allocation-rows
            [categories]="categories()"
            [(rows)]="splitRows"
            [mismatchError]="splitMismatchError()"
          />

          <ui-button type="submit" variant="primary">
            {{ (isEditMode() ? 'templates.save' : 'templates.create') | transloco }}
          </ui-button>
        </form>
      }

      @if (errorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
      @if (serverErrorDetail(); as detail) {
        <ui-alert [message]="detail" testId="template-server-error" />
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
  private readonly transloco = inject(TranslocoService);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

  protected readonly accountOptions = computed<UiSelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  protected readonly typeOptions = computed<UiSelectOption[]>(() => [
    { value: 'expense', label: this.transloco.translate('templates.expense') },
    { value: 'income', label: this.transloco.translate('templates.income') },
  ]);

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

  protected setType(value: string): void {
    this.type.set(value as TemplateType);
  }

  protected setPosition(value: string): void {
    this.position.set(Number(value) || 0);
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
