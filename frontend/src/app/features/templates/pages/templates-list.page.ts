import { Component, computed, inject, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import {
  UiAlertComponent,
  UiButtonComponent,
  UiEmptyStateComponent,
  UiInputComponent,
  UiListCellComponent,
  UiListComponent,
  UiListRowComponent,
  UiLoadingComponent,
  UiPageHeaderComponent,
} from '../../../shared/ui';
import { AccountsService } from '../../accounts/data/accounts.service';
import { TemplatesService } from '../data/templates.service';

/**
 * Templates list (Phase 4 PR5, task 5.1; migrated to the shared/ui kit in
 * Phase 11 PR9, task 11.1): renders `GET /api/templates` with a per-row
 * "apply" action (`POST /api/templates/{id}/apply`, design D56 — the only
 * accepted override is an optional `occurred_on` date, defaulting to today
 * when left blank), an "add template" link, an edit link, and a delete
 * action per row.
 *
 * Template visibility is enforced entirely server-side by
 * `visible_templates(scope, account_id)` — this page never filters or
 * re-derives visibility client-side, it only renders what
 * `GET /api/templates` returns.
 */
@Component({
  selector: 'app-templates-list-page',
  imports: [
    TranslocoPipe,
    UiAlertComponent,
    UiButtonComponent,
    UiEmptyStateComponent,
    UiInputComponent,
    UiListCellComponent,
    UiListComponent,
    UiListRowComponent,
    UiLoadingComponent,
    UiPageHeaderComponent,
  ],
  template: `
    <section class="mx-auto w-full max-w-4xl px-4 py-6">
      <ui-page-header titleKey="templates.title">
        <ui-button link="/templates/new" variant="primary">
          {{ 'templates.create' | transloco }}
        </ui-button>
      </ui-page-header>

      @if (loading()) {
        <ui-loading messageKey="templates.loading" />
      } @else if (loadError()) {
        <ui-alert messageKey="templates.loadError" />
      } @else if (templates().length === 0) {
        <ui-empty-state
          testId="templates-empty"
          titleKey="templates.empty.title"
          messageKey="templates.empty.body"
        >
          <ui-button link="/templates/new" variant="primary">
            {{ 'templates.create' | transloco }}
          </ui-button>
        </ui-empty-state>
      } @else {
        <ui-list testId="templates-list">
          @for (template of templates(); track template.id) {
            <ui-list-row>
              <ui-list-cell labelKey="templates.name">
                <span data-testid="template-name">{{ template.name }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="templates.account">
                <span data-testid="template-account">{{ accountName(template.account_id) }}</span>
              </ui-list-cell>
              <ui-list-cell labelKey="templates.amount">
                <span data-testid="template-amount">{{ template.amount }}</span>
              </ui-list-cell>

              <ui-list-cell>
                <ui-input
                  type="date"
                  [testId]="'template-apply-date-' + template.id"
                  [value]="applyDateFor(template.id)"
                  (valueChange)="setApplyDate(template.id, $event)"
                />
              </ui-list-cell>

              <ui-list-cell class="md:ml-auto">
                <ui-button
                  variant="secondary"
                  size="sm"
                  [testId]="'template-apply-' + template.id"
                  (click)="applyTemplate(template.id)"
                >
                  {{ 'templates.apply' | transloco }}
                </ui-button>
                <ui-button link="/templates/{{ template.id }}/edit" variant="secondary" size="sm">
                  {{ 'templates.edit' | transloco }}
                </ui-button>
                <ui-button variant="danger" size="sm" (click)="deleteTemplate(template.id)">
                  {{ 'templates.delete' | transloco }}
                </ui-button>
              </ui-list-cell>
            </ui-list-row>
          }
        </ui-list>
      }

      @if (actionErrorKey(); as key) {
        <ui-alert [messageKey]="key" />
      }
    </section>
  `,
})
export class TemplatesListPage {
  private readonly templatesService = inject(TemplatesService);
  private readonly accountsService = inject(AccountsService);

  protected readonly templates = this.templatesService.templates;
  protected readonly accounts = this.accountsService.accounts;

  protected readonly loading = signal(true);
  protected readonly loadError = signal(false);
  protected readonly actionErrorKey = signal<string | null>(null);

  /** Per-row optional apply-date override, keyed by template id — left
   * blank means "apply against today", exactly matching
   * `TemplateApplyBody.occurred_on`'s own optionality. */
  private readonly applyDates = signal<Record<string, string>>({});

  private readonly accountNameById = computed(() => {
    const map = new Map<string, string>();
    for (const account of this.accounts()) {
      map.set(account.id, account.name);
    }
    return map;
  });

  constructor() {
    this.accountsService.listAccounts().subscribe();
    this.load();
  }

  protected accountName(accountId: string): string {
    return this.accountNameById().get(accountId) ?? accountId;
  }

  protected applyDateFor(templateId: string): string {
    return this.applyDates()[templateId] ?? '';
  }

  protected setApplyDate(templateId: string, value: string): void {
    this.applyDates.update((dates) => ({ ...dates, [templateId]: value }));
  }

  private load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.templatesService.listTemplates().subscribe({
      next: () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        this.loadError.set(true);
      },
    });
  }

  /** `POST /api/templates/{id}/apply` — sends `occurred_on` only when the
   * row's date picker holds a value; an empty picker sends `{}`, which
   * the server defaults to today (design D56). */
  protected applyTemplate(id: string): void {
    this.actionErrorKey.set(null);
    const occurredOn = this.applyDateFor(id);
    this.templatesService
      .applyTemplate(id, occurredOn ? { occurred_on: occurredOn } : {})
      .subscribe({
        next: () => this.setApplyDate(id, ''),
        error: () => this.actionErrorKey.set('templates.applyError'),
      });
  }

  protected deleteTemplate(id: string): void {
    this.actionErrorKey.set(null);
    this.templatesService.deleteTemplate(id).subscribe({
      next: () => this.load(),
      error: () => this.actionErrorKey.set('templates.deleteError'),
    });
  }
}
