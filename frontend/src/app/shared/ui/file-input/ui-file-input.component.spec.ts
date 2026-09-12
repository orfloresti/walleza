/**
 * `UiFileInputComponent` — Phase UI PR3 (task 3.5). Design D57: the one
 * kit control with an **output** rather than a `model()`, since a file
 * selection is an event, not a value. Mirrors
 * `receipt-upload.component.spec.ts:60-63`'s exact DOM sequence
 * (`Object.defineProperty(input, 'files', …)` then a `change` dispatch)
 * so a future migration of `receipt-upload` onto this component keeps
 * that existing spec's assertions valid.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiFileInputComponent } from './ui-file-input.component';

@Component({
  imports: [UiFileInputComponent],
  template: `
    <ui-file-input
      [accept]="accept()"
      testId="receipt-file-input"
      (fileSelected)="lastFile.set($event)"
    />
  `,
})
class HostComponent {
  accept = signal<string | null>(null);
  lastFile = signal<File | null>(null);
}

function createFile(): File {
  return new File(['fake-bytes'], 'receipt.jpg', { type: 'image/jpeg' });
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiFileInputComponent', () => {
  it('renders the testid on the real native file <input>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="receipt-file-input"]') as HTMLInputElement;

    expect(input).not.toBeNull();
    expect(input.tagName).toBe('INPUT');
    expect(input.type).toBe('file');
  });

  it('selecting a file via defineProperty + change emits it through fileSelected', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="receipt-file-input"]') as HTMLInputElement;
    const file = createFile();

    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(fixture.componentInstance.lastFile()).toBe(file);
  });

  it('forwards accept onto the native element', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.accept.set('image/jpeg,image/png');
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const input = el.querySelector('[data-testid="receipt-file-input"]') as HTMLInputElement;

    expect(input.getAttribute('accept')).toBe('image/jpeg,image/png');
  });
});
