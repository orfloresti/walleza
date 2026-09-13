import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiBadgeComponent,
  UiButtonComponent,
  UiCardComponent,
  UiCheckboxComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiInputComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AccountsService } from '../data/accounts.service';

/**
 * Accounts list/CRUD view (Phase 1 PR4b, tasks 8.1/8.2): renders
 * `GET /api/accounts` (toggle between active and archived, task 8.1),
 * a create form covering name/currency/exchange_rate/initial_funds/
 * is_personal (task 8.2), and an inline archive action per row —
 * `PATCH { archived: true }`, never DELETE (there is no DELETE route,
 * design's Interfaces/Contracts table, decision 6). Deliberately
 * unpolished per the proposal: functionally correct, not styled, no
 * separate edit view (archiving is the only mutation this phase's UI
 * needs beyond create).
 *
 * Personal-account visibility (design D15/spec `account-visibility`) is
 * enforced entirely server-side by `visible_accounts(scope)` — this page
 * never filters or re-derives visibility client-side, it only renders
 * what `GET /api/accounts` returns and marks `is_personal` rows with a
 * badge so a shared vs. personal account is visually distinguishable.
 *
 * Phase UI (PR6) — migrated to the `shared/ui/` kit. The list now has a
 * fourth, structurally separate empty-state branch (D64).
 *
 * **Deviation from design/tasks, documented per PR5's precedent**: the
 * show-archived toggle keeps its plain native `<input type="checkbox">`
 * with `[checked]="showArchived()" (change)="toggleArchived()"` —
 * unchanged from before this migration — rather than routing through
 * `ui-checkbox`'s `checkedChange` output as design/tasks specified.
 * Verified empirically (Angular core, `createModelSignal`): a
 * `model()`'s setter only calls `emitterRef.emit(...)` when the new
 * value is NOT equal to the signal's current value
 * (`if (!node.equal(node.value, newValue)) { ...; emitterRef.emit(...) }`
 * in `@angular/core`). `accounts-list.page.spec.ts`'s invariant-3 spec
 * dispatches a bare `change` while `.checked` is already `false` (its
 * unchanged default) — a false→false "change" — so `ui-checkbox`'s
 * `checkedChange` NEVER fires in that exact scenario, regardless of
 * whether the page binds `[checked]/(checkedChange)` (as tasks.md
 * specifies) or `[(checked)]` (what tasks.md forbids): both route
 * through the same equality-gated `model()` setter and both would
 * silently drop the event, so `toggleArchived()` would never run and
 * the `archived=true` re-request would never fire. `ui-checkbox` is
 * built for VALUE semantics; this toggle needs EVENT semantics (fire on
 * every native `change`, never gated by equality) — the same reasoning
 * design already applied to make `ui-file-input` use `output()` instead
 * of `model()` ("a file selection is an event, not a value"). No kit
 * component change is in scope for this PR, so the toggle stays native.
 * Flag for a future design revision: `ui-checkbox` may need a raw
 * `(nativeChange)` output alongside its model for exactly this case.
 */
@Component({
  selector: 'app-accounts-list-page',
  imports: [
    FormsModule,
    TranslocoPipe,
    UiAlertComponent,
    UiBadgeComponent,
    UiButtonComponent,
    UiCardComponent,
    UiCheckboxComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiInputComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-4xl px-4 py-6">
      <ui-page-header titleKey="accounts.title" />

      <ui-field labelKey="accounts.showArchived" layout="inline">
        <!-- Deliberately a plain native checkbox, not ui-checkbox — see
             the class doc comment above (model() equality gate). -->
        <input
          type="checkbox"
          data-testid="show-archived-toggle"
          [checked]="showArchived()"
          (change)="toggleArchived()"
        />
      </ui-field>

      @if (loading()) {
        <ui-loading messageKey="accounts.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="accounts.loadError" />
      } @else if (accounts().length === 0) {
        <ui-empty-state
          testId="accounts-empty"
          titleKey="accounts.empty.title"
          messageKey="accounts.empty.body"
        />
      } @else {
        <ui-list testId="accounts-list">
          @for (account of accounts(); track account.id) {
            <ui-list-row>
              <ui-list-cell labelKey="accounts.name">
                <span>{{ account.name }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="accounts.currency">
                <span>{{ account.currency }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="accounts.initialFunds">
                <span>{{ account.initial_funds }}</span>
              </ui-list-cell>
              @if (account.is_personal) {
                <ui-list-cell>
                  <ui-badge variant="personal" testId="personal-badge">
                    {{ 'accounts.personalBadge' | transloco }}
                  </ui-badge>
                </ui-list-cell>
              }
              @if (account.archived) {
                <ui-list-cell>
                  <ui-badge variant="archived" testId="archived-badge">
                    {{ 'accounts.archivedBadge' | transloco }}
                  </ui-badge>
                </ui-list-cell>
              } @else {
                <ui-list-cell class="md:ml-auto">
                  <ui-button variant="secondary" size="sm" (click)="archiveAccount(account.id)">
                    {{ 'accounts.archive' | transloco }}
                  </ui-button>
                </ui-list-cell>
              }
            </ui-list-row>
          }
        </ui-list>
      }

      <ui-card>
        <form (ngSubmit)="createAccount()" class="flex flex-col gap-3">
          <h2 class="text-lg font-semibold text-on-surface">
            {{ 'accounts.createTitle' | transloco }}
          </h2>

          <ui-field labelKey="accounts.name">
            <ui-input name="name" [required]="true" [(value)]="name" />
          </ui-field>

          <ui-field labelKey="accounts.currency">
            <ui-input name="currency" [required]="true" [maxLength]="3" [(value)]="currency" />
          </ui-field>

          <ui-field labelKey="accounts.exchangeRate">
            <ui-input name="exchangeRate" [(value)]="exchangeRate" />
          </ui-field>

          <ui-field labelKey="accounts.initialFunds">
            <ui-input name="initialFunds" [(value)]="initialFunds" />
          </ui-field>

          <ui-field labelKey="accounts.isPersonal" layout="inline">
            <ui-checkbox name="isPersonal" [(checked)]="isPersonal" />
          </ui-field>

          <ui-button type="submit" variant="primary">{{ 'accounts.create' | transloco }}</ui-button>
        </form>
      </ui-card>

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
    </section>
  `,
})
export class AccountsListPage {
  private readonly accountsService = inject(AccountsService);

  protected readonly accounts = this.accountsService.accounts;
  protected readonly showArchived = signal(false);
  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  protected readonly name = signal('');
  protected readonly currency = signal('');
  protected readonly exchangeRate = signal('1');
  protected readonly initialFunds = signal('0');
  protected readonly isPersonal = signal(false);

  constructor() {
    this.load();
  }

  protected toggleArchived(): void {
    this.showArchived.set(!this.showArchived());
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.accountsService.listAccounts(this.showArchived()).subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  protected createAccount(): void {
    this.actionErrorKey.set(null);
    this.accountsService
      .createAccount({
        name: this.name(),
        currency: this.currency().toUpperCase(),
        // Money fields travel as strings the whole way (design D19) —
        // exactly the form field's raw value, never parsed into a JS
        // number and written back, so precision is never at risk.
        exchange_rate: this.exchangeRate(),
        initial_funds: this.initialFunds(),
        is_personal: this.isPersonal(),
      })
      .subscribe({
        next: () => {
          this.name.set('');
          this.currency.set('');
          this.exchangeRate.set('1');
          this.initialFunds.set('0');
          this.isPersonal.set(false);
          this.load();
        },
        error: () => this.actionErrorKey.set('accounts.createError'),
      });
  }

  protected archiveAccount(id: string): void {
    this.actionErrorKey.set(null);
    this.accountsService.archiveAccount(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('accounts.archiveError'),
    });
  }
}
