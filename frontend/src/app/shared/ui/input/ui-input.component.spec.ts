/**
 * `UiInputComponent` — Phase UI PR2 (task 2.4). A controlled component on
 * `model()` (design D57), mirroring `split-allocation-rows.component.ts`'s
 * `[(rows)]` convention: `(input)` updates the `value` model, and the
 * testid resolves to the real native `<input>` (D58), so
 * `(querySelector('[data-testid="…"]') as HTMLInputElement).value = x`
 * assignments in existing page specs keep working after migration.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiInputComponent } from './ui-input.component';

@Component({
  imports: [UiInputComponent],
  template: `
    <ui-input
      [(value)]="value"
      [type]="type()"
      [name]="name()"
      [required]="required()"
      [maxLength]="maxLength()"
      [disabled]="disabled()"
      [invalid]="invalid()"
      testId="account-name"
    />
  `,
})
class HostComponent {
  value = signal('');
  type = signal<'text' | 'number' | 'date'>('text');
  name = signal<string | null>(null);
  required = signal(false);
  maxLength = signal<number | null>(null);
  disabled = signal(false);
  invalid = signal(false);
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiInputComponent', () => {
  it('renders the testid on the real native <input>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="account-name"]');
    expect(input).not.toBeNull();
    expect(input!.tagName).toBe('INPUT');
  });

  it('dispatching (input) updates the value model, and the model updates the DOM value', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="account-name"]') as HTMLInputElement;

    input.value = 'Checking';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(fixture.componentInstance.value()).toBe('Checking');

    fixture.componentInstance.value.set('Savings');
    fixture.detectChanges();
    expect(input.value).toBe('Savings');
  });

  it('forwards type, name, required, maxlength and disabled onto the native element', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.type.set('date');
    fixture.componentInstance.name.set('occurred_on');
    fixture.componentInstance.required.set(true);
    fixture.componentInstance.maxLength.set(10);
    fixture.componentInstance.disabled.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="account-name"]') as HTMLInputElement;

    expect(input.getAttribute('type')).toBe('date');
    expect(input.getAttribute('name')).toBe('occurred_on');
    expect(input.getAttribute('required')).toBe('');
    expect(input.getAttribute('maxlength')).toBe('10');
    expect(input.disabled).toBe(true);
  });
});
