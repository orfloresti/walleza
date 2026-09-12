/**
 * `UiCheckboxComponent` — Phase UI PR3 (task 3.4). Mirrors invariant 3
 * from design D57/`accounts-list.page.spec.ts:128-131`: a bare `change`
 * event (without ever setting `.checked` first) must emit the DOM's
 * *current* `.checked` value, never an assumed toggle of the model's
 * prior value. A naive `checked.set(!checked())` implementation would
 * pass a manual click-driven test but silently break that existing page
 * spec's `archived=true` query-param assertion.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiCheckboxComponent } from './ui-checkbox.component';

@Component({
  imports: [UiCheckboxComponent],
  template: `
    <ui-checkbox
      [(checked)]="checked"
      [name]="name()"
      [disabled]="disabled()"
      testId="show-archived-toggle"
    />
  `,
})
class HostComponent {
  checked = signal(false);
  name = signal<string | null>(null);
  disabled = signal(false);
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiCheckboxComponent', () => {
  it('renders the testid on the real native checkbox <input>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="show-archived-toggle"]') as HTMLInputElement;

    expect(input).not.toBeNull();
    expect(input.tagName).toBe('INPUT');
    expect(input.type).toBe('checkbox');
  });

  it(
    'a bare change (without setting .checked) emits the DOM current .checked, ' +
      'not an assumed toggle of the prior model value',
    async () => {
      const fixture = await createFixture();
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const input = el.querySelector('[data-testid="show-archived-toggle"]') as HTMLInputElement;

      // The model starts false; the DOM's .checked also starts false. A
      // bare `change` dispatch (no assignment to .checked) must read the
      // DOM's current value (false), not flip the model to true.
      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(fixture.componentInstance.checked()).toBe(false);
    },
  );

  it('setting .checked then dispatching change updates the checked model', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="show-archived-toggle"]') as HTMLInputElement;

    input.checked = true;
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(fixture.componentInstance.checked()).toBe(true);

    fixture.componentInstance.checked.set(false);
    fixture.detectChanges();
    expect(input.checked).toBe(false);
  });

  it('forwards name and disabled onto the native element', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.name.set('showArchived');
    fixture.componentInstance.disabled.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="show-archived-toggle"]') as HTMLInputElement;

    expect(input.getAttribute('name')).toBe('showArchived');
    expect(input.disabled).toBe(true);
  });
});
