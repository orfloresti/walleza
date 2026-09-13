import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiCheckboxComponent,
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
import {
  RecurringCreate,
  RecurringPeriod,
  RecurringType,
  RecurringUpdate,
  ReminderLocale,
  RecurringService,
} from '../data/recurring.service';

/**
 * Create/edit recurring-transaction form (Phase 4 PR5, task 5.2; migrated
 * to the shared/ui kit in Phase 11 PR9, task 11.2): account, type,
 * amount, notes, is_refund, is_subscription, repeat_every, period,
 * starts_on (create-only, design D49's immutable anchor), ends_on,
 * reminder_days_before, reminder_locale, and an inline split-allocation
 * editor reused verbatim from `features/transactions/ui/split-allocation-
 * rows`.
 *
 * `starts_on` is rendered ONLY in create mode — `RecurringUpdate` carries
 * no such field at all (design D49), so there is nothing for an edit-mode
 * submission to send even if the input were shown; hiding it removes a
 * dead control from the edit form entirely.
 *
 * Design D48's backfill warning: when the chosen `starts_on` is strictly
 * before today, every missed occurrence between then and today is
 * generated and posted as REAL transactions once the recurrence is
 * saved (the catch-up bound generates, it never fast-forwards silently) —
 * rendered as `ui-alert variant="warning" [messageKey]="'recurring.
 * backfillWarning'"` directly below the `starts_on` input, whenever that
 * condition holds, and never otherwise. This is a TRANSLATED, static copy
 * string, unlike the verbatim 422 branch below — it never carries
 * server-controlled content, so routing it through `messageKey` (not
 * `message`) is correct here.
 *
 * A `:id` route param switches the form into edit mode. Money is kept as
 * a raw `string` end-to-end (design D19).
 */
@Component({
  selector: 'app-recurring-form-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    SplitAllocationRowsComponent,
    UiAlertComponent,
    UiButtonComponent,
    UiCheckboxComponent,
    UiFieldComponent,
    UiInputComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
    UiSelectComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-2xl px-4 py-6">
      <ui-page-header
        [titleKey]="isEditMode() ? 'recurring.editTitle' : 'recurring.createTitle'"
      />

      @if (loading()) {
        <ui-loading messageKey="recurring.loading" />
      } @else {
        <form (ngSubmit)="save()" class="flex flex-col gap-3">
          <ui-field labelKey="recurring.account">
            <ui-select
              name="accountId"
              [required]="true"
              testId="recurring-account-select"
              [options]="accountOptions()"
              placeholderKey="recurring.selectAccount"
              [value]="accountId()"
              (valueChange)="accountId.set($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.type">
            <ui-select
              name="type"
              testId="recurring-type-select"
              [options]="typeOptions()"
              [value]="type()"
              (valueChange)="setType($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.amount">
            <ui-input
              name="amount"
              [required]="true"
              testId="recurring-amount-input"
              [value]="amount()"
              (valueChange)="amount.set($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.notes">
            <ui-input name="notes" [value]="notes()" (valueChange)="notes.set($event)" />
          </ui-field>

          <ui-field labelKey="recurring.isRefund" layout="inline">
            <ui-checkbox name="isRefund" [(checked)]="isRefund" />
          </ui-field>

          <ui-field labelKey="recurring.isSubscription" layout="inline">
            <ui-checkbox
              name="isSubscription"
              testId="recurring-is-subscription-checkbox"
              [(checked)]="isSubscription"
            />
          </ui-field>

          <ui-field labelKey="recurring.repeatEvery">
            <ui-input
              type="number"
              name="repeatEvery"
              [required]="true"
              testId="recurring-repeat-every-input"
              [value]="repeatEvery().toString()"
              (valueChange)="setRepeatEvery($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.period">
            <ui-select
              name="period"
              testId="recurring-period-select"
              [options]="periodOptions()"
              [value]="period()"
              (valueChange)="setPeriod($event)"
            />
          </ui-field>

          @if (!isEditMode()) {
            <ui-field labelKey="recurring.startsOn">
              <ui-input
                type="date"
                name="startsOn"
                [required]="true"
                testId="recurring-starts-on-input"
                [value]="startsOn()"
                (valueChange)="startsOn.set($event)"
              />
            </ui-field>
            @if (showBackfillWarning()) {
              <ui-alert
                variant="warning"
                testId="recurring-backfill-warning"
                messageKey="recurring.backfillWarning"
              />
            }
          }

          <ui-field labelKey="recurring.endsOn">
            <ui-input
              type="date"
              name="endsOn"
              testId="recurring-ends-on-input"
              [value]="endsOn()"
              (valueChange)="endsOn.set($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.reminderDaysBefore">
            <ui-input
              type="number"
              name="reminderDaysBefore"
              testId="recurring-reminder-days-input"
              [value]="reminderDaysBeforeText()"
              (valueChange)="setReminderDaysBefore($event)"
            />
          </ui-field>

          <ui-field labelKey="recurring.reminderLocale">
            <ui-select
              name="reminderLocale"
              testId="recurring-reminder-locale-select"
              [options]="reminderLocaleOptions"
              [value]="reminderLocale()"
              (valueChange)="setReminderLocale($event)"
            />
          </ui-field>

          <app-split-allocation-rows
            [categories]="categories()"
            [(rows)]="splitRows"
            [mismatchError]="splitMismatchError()"
          />

          <ui-button type="submit" variant="primary">
            {{ (isEditMode() ? 'recurring.save' : 'recurring.create') | transloco }}
          </ui-button>
        </form>
      }

      @if (errorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
      @if (serverErrorDetail(); as detail) {
        <ui-alert [message]="detail" testId="recurring-server-error" />
      }
    </section>
  `,
})
export class RecurringFormPage {
  private readonly recurringService = inject(RecurringService);
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
    { value: 'expense', label: this.transloco.translate('recurring.expense') },
    { value: 'income', label: this.transloco.translate('recurring.income') },
  ]);

  protected readonly periodOptions = computed<UiSelectOption[]>(() => [
    { value: 'day', label: this.transloco.translate('recurring.periodDay') },
    { value: 'week', label: this.transloco.translate('recurring.periodWeek') },
    { value: 'month', label: this.transloco.translate('recurring.periodMonth') },
    { value: 'year', label: this.transloco.translate('recurring.periodYear') },
  ]);

  protected readonly reminderLocaleOptions: UiSelectOption[] = [
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Español' },
  ];

  protected readonly recurringId = signal<string | null>(null);
  protected readonly isEditMode = signal(false);
  protected readonly loading = signal(true);
  protected readonly errorKey = signal<string | null>(null);
  protected readonly serverErrorDetail = signal<string | null>(null);

  protected readonly accountId = signal('');
  protected readonly type = signal<RecurringType>('expense');
  protected readonly amount = signal('');
  protected readonly notes = signal('');
  protected readonly isRefund = signal(false);
  protected readonly isSubscription = signal(false);
  protected readonly repeatEvery = signal(1);
  protected readonly period = signal<RecurringPeriod>('month');
  protected readonly startsOn = signal('');
  protected readonly endsOn = signal('');
  protected readonly reminderDaysBefore = signal<number | null>(null);
  protected readonly reminderLocale = signal<ReminderLocale>('en');

  protected readonly reminderDaysBeforeText = computed(() => {
    const value = this.reminderDaysBefore();
    return value === null ? '' : value.toString();
  });

  protected readonly splitRows = signal<SplitRowValue[]>([]);
  protected readonly splitMismatchError = signal<SplitMismatchError | null>(null);

  /** Design D48: true whenever the chosen `starts_on` is strictly before
   * today. ISO `YYYY-MM-DD` strings sort lexicographically identically to
   * chronological order, so a direct string comparison against today's
   * ISO date avoids constructing a `Date` (and its timezone ambiguity)
   * entirely. */
  protected readonly showBackfillWarning = computed(() => {
    const value = this.startsOn();
    if (!value) return false;
    return value < new Date().toISOString().slice(0, 10);
  });

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.categoriesService.listCategories().subscribe();

    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.recurringId.set(id);
      this.isEditMode.set(true);
      this.loadExisting(id);
    } else {
      this.loading.set(false);
    }
  }

  protected setType(value: string): void {
    this.type.set(value as RecurringType);
  }

  protected setPeriod(value: string): void {
    this.period.set(value as RecurringPeriod);
  }

  protected setReminderLocale(value: string): void {
    this.reminderLocale.set(value as ReminderLocale);
  }

  protected setRepeatEvery(value: string): void {
    this.repeatEvery.set(Number(value) || 0);
  }

  protected setReminderDaysBefore(value: string): void {
    this.reminderDaysBefore.set(value === '' ? null : Number(value));
  }

  private loadExisting(id: string): void {
    this.loading.set(true);
    this.recurringService.getRecurring(id).subscribe({
      next: (recurring) => {
        this.accountId.set(recurring.account_id);
        this.type.set(recurring.type);
        this.amount.set(recurring.amount);
        this.notes.set(recurring.notes ?? '');
        this.isRefund.set(recurring.is_refund);
        this.isSubscription.set(recurring.is_subscription);
        this.repeatEvery.set(recurring.repeat_every);
        this.period.set(recurring.period);
        this.startsOn.set(recurring.starts_on);
        this.endsOn.set(recurring.ends_on ?? '');
        this.reminderDaysBefore.set(recurring.reminder_days_before);
        this.reminderLocale.set(recurring.reminder_locale);
        this.splitRows.set(
          recurring.splits.map((split) => ({ category_id: split.category_id, amount: split.amount })),
        );
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.errorKey.set('recurring.loadError');
      },
    });
  }

  protected save(): void {
    this.errorKey.set(null);
    this.serverErrorDetail.set(null);
    this.splitMismatchError.set(null);

    const isEdit = this.isEditMode();
    const id = this.recurringId();

    const rows = this.splitRows();
    const splits =
      rows.length > 0
        ? rows.map((row) => ({ category_id: row.category_id, amount: row.amount }))
        : undefined;

    const request = isEdit && id
      ? this.recurringService.updateRecurring(id, {
          account_id: this.accountId(),
          type: this.type(),
          amount: this.amount(),
          notes: this.notes() || null,
          is_refund: this.isRefund(),
          is_subscription: this.isSubscription(),
          repeat_every: this.repeatEvery(),
          period: this.period(),
          ends_on: this.endsOn() || null,
          reminder_days_before: this.reminderDaysBefore(),
          reminder_locale: this.reminderLocale(),
          ...(splits ? { splits } : {}),
        } satisfies RecurringUpdate)
      : this.recurringService.createRecurring({
          account_id: this.accountId(),
          type: this.type(),
          amount: this.amount(),
          notes: this.notes() || null,
          is_refund: this.isRefund(),
          is_subscription: this.isSubscription(),
          repeat_every: this.repeatEvery(),
          period: this.period(),
          starts_on: this.startsOn(),
          ends_on: this.endsOn() || null,
          reminder_days_before: this.reminderDaysBefore(),
          reminder_locale: this.reminderLocale(),
          ...(splits ? { splits } : {}),
        } satisfies RecurringCreate);

    request.subscribe({
      next: () => void this.router.navigateByUrl('/recurring'),
      error: (err: HttpErrorResponse) => {
        if (err.status === 422) {
          const mismatch = parseSplitMismatchError(
            (err.error as { detail?: unknown } | null)?.detail,
          );
          if (mismatch) {
            this.splitMismatchError.set(mismatch);
            return;
          }
          const detail = (err.error as { detail?: unknown } | null)?.detail;
          if (typeof detail === 'string') {
            this.serverErrorDetail.set(detail);
            return;
          }
          this.errorKey.set('recurring.saveError');
          return;
        }
        this.errorKey.set('recurring.saveError');
      },
    });
  }
}
