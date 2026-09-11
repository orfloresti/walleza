import { Component, computed, inject, signal } from '@angular/core';
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
import {
  RecurringCreate,
  RecurringPeriod,
  RecurringType,
  RecurringUpdate,
  ReminderLocale,
  RecurringService,
} from '../data/recurring.service';

/**
 * Create/edit recurring-transaction form (Phase 4 PR5, task 5.2): account,
 * type, amount, notes, is_refund, is_subscription, repeat_every, period,
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
 * `recurring.backfillWarning` is rendered inline, directly below the
 * `starts_on` input, whenever that condition holds, and never otherwise.
 *
 * A `:id` route param switches the form into edit mode. Money is kept as
 * a raw `string` end-to-end (design D19).
 */
@Component({
  selector: 'app-recurring-form-page',
  imports: [FormsModule, TranslocoPipe, SplitAllocationRowsComponent],
  template: `
    <section>
      <h1>{{ (isEditMode() ? 'recurring.editTitle' : 'recurring.createTitle') | transloco }}</h1>

      @if (loading()) {
        <p>{{ 'recurring.loading' | transloco }}</p>
      } @else {
        <form (ngSubmit)="save()">
          <label>
            {{ 'recurring.account' | transloco }}
            <select
              name="accountId"
              required
              data-testid="recurring-account-select"
              [ngModel]="accountId()"
              (ngModelChange)="accountId.set($event)"
            >
              <option value="">{{ 'recurring.selectAccount' | transloco }}</option>
              @for (account of accounts(); track account.id) {
                <option [value]="account.id">{{ account.name }}</option>
              }
            </select>
          </label>

          <label>
            {{ 'recurring.type' | transloco }}
            <select
              name="type"
              data-testid="recurring-type-select"
              [ngModel]="type()"
              (ngModelChange)="type.set($event)"
            >
              <option value="expense">{{ 'recurring.expense' | transloco }}</option>
              <option value="income">{{ 'recurring.income' | transloco }}</option>
            </select>
          </label>

          <label>
            {{ 'recurring.amount' | transloco }}
            <input
              type="text"
              name="amount"
              required
              data-testid="recurring-amount-input"
              [ngModel]="amount()"
              (ngModelChange)="amount.set($event)"
            />
          </label>

          <label>
            {{ 'recurring.notes' | transloco }}
            <input type="text" name="notes" [ngModel]="notes()" (ngModelChange)="notes.set($event)" />
          </label>

          <label>
            <input
              type="checkbox"
              name="isRefund"
              [ngModel]="isRefund()"
              (ngModelChange)="isRefund.set($event)"
            />
            {{ 'recurring.isRefund' | transloco }}
          </label>

          <label>
            <input
              type="checkbox"
              name="isSubscription"
              data-testid="recurring-is-subscription-checkbox"
              [ngModel]="isSubscription()"
              (ngModelChange)="isSubscription.set($event)"
            />
            {{ 'recurring.isSubscription' | transloco }}
          </label>

          <label>
            {{ 'recurring.repeatEvery' | transloco }}
            <input
              type="number"
              name="repeatEvery"
              required
              min="1"
              data-testid="recurring-repeat-every-input"
              [ngModel]="repeatEvery()"
              (ngModelChange)="repeatEvery.set($event)"
            />
          </label>

          <label>
            {{ 'recurring.period' | transloco }}
            <select
              name="period"
              data-testid="recurring-period-select"
              [ngModel]="period()"
              (ngModelChange)="period.set($event)"
            >
              <option value="day">{{ 'recurring.periodDay' | transloco }}</option>
              <option value="week">{{ 'recurring.periodWeek' | transloco }}</option>
              <option value="month">{{ 'recurring.periodMonth' | transloco }}</option>
              <option value="year">{{ 'recurring.periodYear' | transloco }}</option>
            </select>
          </label>

          @if (!isEditMode()) {
            <label>
              {{ 'recurring.startsOn' | transloco }}
              <input
                type="date"
                name="startsOn"
                required
                data-testid="recurring-starts-on-input"
                [ngModel]="startsOn()"
                (ngModelChange)="startsOn.set($event)"
              />
            </label>
            @if (showBackfillWarning()) {
              <p role="alert" data-testid="recurring-backfill-warning">
                {{ 'recurring.backfillWarning' | transloco }}
              </p>
            }
          }

          <label>
            {{ 'recurring.endsOn' | transloco }}
            <input
              type="date"
              name="endsOn"
              data-testid="recurring-ends-on-input"
              [ngModel]="endsOn()"
              (ngModelChange)="endsOn.set($event)"
            />
          </label>

          <label>
            {{ 'recurring.reminderDaysBefore' | transloco }}
            <input
              type="number"
              name="reminderDaysBefore"
              min="0"
              max="30"
              data-testid="recurring-reminder-days-input"
              [ngModel]="reminderDaysBefore()"
              (ngModelChange)="reminderDaysBefore.set($event)"
            />
          </label>

          <label>
            {{ 'recurring.reminderLocale' | transloco }}
            <select
              name="reminderLocale"
              data-testid="recurring-reminder-locale-select"
              [ngModel]="reminderLocale()"
              (ngModelChange)="reminderLocale.set($event)"
            >
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </label>

          <app-split-allocation-rows
            [categories]="categories()"
            [(rows)]="splitRows"
            [mismatchError]="splitMismatchError()"
          />

          <button type="submit">
            {{ (isEditMode() ? 'recurring.save' : 'recurring.create') | transloco }}
          </button>
        </form>
      }

      @if (errorKey(); as key) {
        <p role="alert">{{ key | transloco }}</p>
      }
      @if (serverErrorDetail(); as detail) {
        <p role="alert" data-testid="recurring-server-error">{{ detail }}</p>
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

  protected readonly accounts = this.accountsService.accounts;
  protected readonly categories = this.categoriesService.categories;

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
          this.errorKey.set('recurring.saveError');
          return;
        }
        this.errorKey.set('recurring.saveError');
      },
    });
  }
}
