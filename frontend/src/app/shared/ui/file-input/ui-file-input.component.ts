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
  /** Phase 9 addition (design D133): `"environment"`/`"user"` forwards
   * to the native `capture` attribute so mobile browsers open the camera
   * directly rather than a generic file picker. `null` (the default)
   * omits the attribute entirely, preserving every existing caller's
   * generic-picker behavior unchanged. */
  readonly capture = input<string | null>(null);
  readonly fileSelected = output<File | null>();

  protected onChange(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    this.fileSelected.emit(file);
  }
}
