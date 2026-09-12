/**
 * `UiSelectComponent` — Phase UI PR3 (tasks 3.2/3.3). Task 3.2 is a
 * REGRESSION GUARD for design D57's rejected alternative: projecting
 * page-authored `<option>` children into `ui-select` via `<ng-content>`.
 * That alternative is rejected because Angular's `NgSelectOption`
 * injects its parent `SelectControlValueAccessor` with `@Optional()
 * @Host()`, and `@Host()` does not cross a content-projection boundary —
 * a projected `<option>` never registers in the select's `_optionMap`,
 * so `writeValue` silently falls through to `selectedIndex = -1`. This
 * spec must FAIL if `ui-select` is ever "simplified" back to projected
 * `<option>` children instead of rendering them from its own `options`
 * input.
 *
 * Task 3.3 mirrors `transfers-list.page.spec.ts:138-139`'s exact DOM
 * sequence (`select.value = x; select.dispatchEvent(new Event('change'))`)
 * to prove the controlled-component shape (D57) and testid placement
 * (D58) together keep that existing page spec's assertions valid.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiSelectComponent, UiSelectOption } from './ui-select.component';

const OPTIONS: UiSelectOption[] = [
  { value: 'acc-1', label: 'Checking' },
  { value: 'acc-2', label: 'Savings' },
];

const TRANSLATIONS = {
  transfers: {
    filterAll: 'All accounts',
  },
};

@Component({
  imports: [UiSelectComponent],
  template: `
    <ui-select
      [options]="options()"
      placeholderKey="transfers.filterAll"
      [(value)]="value"
      [name]="name()"
      [required]="required()"
      [disabled]="disabled()"
      testId="filter-account"
    />
  `,
})
class HostComponent {
  options = signal<UiSelectOption[]>(OPTIONS);
  value = signal('');
  name = signal<string | null>(null);
  required = signal(false);
  disabled = signal(false);
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({
    imports: [
      HostComponent,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
  }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiSelectComponent', () => {
  it(
    'renders the testid on the real native <select>, with every supplied ' +
      'option as a real child <option> — regression guard for the ' +
      'rejected content-projection alternative (D57)',
    async () => {
      const fixture = await createFixture();
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const select = el.querySelector('[data-testid="filter-account"]') as HTMLSelectElement;

      expect(select).not.toBeNull();
      expect(select.tagName).toBe('SELECT');

      const optionValues = Array.from(select.options).map((option) => option.value);
      for (const supplied of OPTIONS) {
        expect(optionValues).toContain(supplied.value);
      }
      const checkingOption = Array.from(select.options).find((o) => o.value === 'acc-1');
      expect(checkingOption?.textContent?.trim()).toBe('Checking');
    },
  );

  it('setting .value and dispatching change updates the value model and emits valueChange', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const select = el.querySelector('[data-testid="filter-account"]') as HTMLSelectElement;

    select.value = 'acc-1';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(fixture.componentInstance.value()).toBe('acc-1');

    fixture.componentInstance.value.set('acc-2');
    fixture.detectChanges();
    expect(select.value).toBe('acc-2');
  });

  it('forwards name, required and disabled onto the native element', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.name.set('filterAccount');
    fixture.componentInstance.required.set(true);
    fixture.componentInstance.disabled.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const select = el.querySelector('[data-testid="filter-account"]') as HTMLSelectElement;

    expect(select.getAttribute('name')).toBe('filterAccount');
    expect(select.getAttribute('required')).toBe('');
    expect(select.disabled).toBe(true);
  });
});
