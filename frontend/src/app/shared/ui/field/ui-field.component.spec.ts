/**
 * `UiFieldComponent` — Phase UI PR2 (task 2.3). A real `<label>` wraps
 * the projected control, giving native label/control association with
 * no `for`/`id` wiring required from the page. When an error is present,
 * the wrapped control's `aria-describedby` picks up the error (and hint)
 * paragraph id, per spec's "Requirement: Form Control Components" /
 * "ui-field associates label and error with its control" scenario.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiFieldComponent } from './ui-field.component';

const TRANSLATIONS = {
  account: {
    name: 'Account name',
    hint: 'Shown to every workspace member',
    error: 'Account name is required',
  },
};

@Component({
  imports: [UiFieldComponent],
  template: `
    <ui-field [labelKey]="'account.name'" [hintKey]="hintKey" [errorKey]="errorKey">
      <input data-testid="account-name" />
    </ui-field>
  `,
})
class HostComponent {
  hintKey: string | null = null;
  errorKey: string | null = null;
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

describe('UiFieldComponent', () => {
  it('wraps the projected control in a real <label>, natively associated with it', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const label = el.querySelector('label') as HTMLLabelElement;
    const input = el.querySelector('[data-testid="account-name"]') as HTMLInputElement;

    expect(label).not.toBeNull();
    expect(label.textContent).toContain('Account name');
    expect(label.control).toBe(input);
  });

  it('exposes the error text to assistive tech via aria-describedby on the control', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.errorKey = 'account.error';
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="account-name"]') as HTMLInputElement;
    const describedBy = input.getAttribute('aria-describedby');

    expect(describedBy).toBeTruthy();
    const errorEl = document.getElementById(describedBy!.split(' ')[0]);
    expect(errorEl?.textContent).toContain('Account name is required');
  });

  it('does not set aria-describedby when there is no hint or error', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="account-name"]') as HTMLInputElement;
    expect(input.hasAttribute('aria-describedby')).toBe(false);
  });
});
