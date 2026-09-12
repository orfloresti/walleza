import { Component, input, output } from '@angular/core';

/**
 * Design D57 — the one kit control with an **output** rather than a
 * `model()`: a file selection is an event, not a value the parent should
 * echo back. `(change)` reads `(event.target as HTMLInputElement)
 * .files?.[0] ?? null` — exactly the shape
 * `receipt-upload.component.spec.ts:60-63` drives via
 * `Object.defineProperty(input, 'files', …)` then a `change` dispatch.
 */
@Component({
  selector: 'ui-file-input',
  templateUrl: './ui-file-input.component.html',
})
export class UiFileInputComponent {
  readonly accept = input<string | null>(null);
  readonly disabled = input(false);
  readonly testId = input<string | null>(null);
  readonly fileSelected = output<File | null>();

  protected onChange(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    this.fileSelected.emit(file);
  }
}
