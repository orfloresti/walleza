import { Component, computed, effect, ElementRef, input, viewChild } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

let nextFieldId = 0;

/**
 * Design D57/D63 — a real `<label>` wraps the projected native control
 * (`<ng-content>`), which is the standard implicit label/control
 * association: no `for`/`id` pairing is needed for `label.control` to
 * resolve to the wrapped control (spec `design-system` — "ui-field
 * associates label and error with its control").
 *
 * Hint/error text render as siblings of the label with stable ids; the
 * wrapped native control's `aria-describedby` is kept in sync with those
 * ids via a constructor `effect()` that queries the label's own subtree
 * for the first native form control — this component has no other way
 * to reach an arbitrary projected element's attributes.
 */
@Component({
  selector: 'ui-field',
  imports: [TranslocoPipe],
  templateUrl: './ui-field.component.html',
})
export class UiFieldComponent {
  private readonly fieldId = `ui-field-${nextFieldId++}`;

  readonly labelKey = input.required<string>();
  readonly hintKey = input<string | null>(null);
  readonly errorKey = input<string | null>(null);
  readonly layout = input<'stacked' | 'inline'>('stacked');

  protected readonly hintId = `${this.fieldId}-hint`;
  protected readonly errorId = `${this.fieldId}-error`;

  protected readonly describedBy = computed(() => {
    const ids: string[] = [];
    if (this.errorKey()) {
      ids.push(this.errorId);
    }
    if (this.hintKey()) {
      ids.push(this.hintId);
    }
    return ids.length > 0 ? ids.join(' ') : null;
  });

  private readonly labelRef = viewChild.required<ElementRef<HTMLLabelElement>>('label');

  constructor() {
    effect(() => {
      const describedBy = this.describedBy();
      const control = this.labelRef().nativeElement.querySelector<HTMLElement>(
        'input, select, textarea',
      );
      if (!control) {
        return;
      }
      if (describedBy) {
        control.setAttribute('aria-describedby', describedBy);
      } else {
        control.removeAttribute('aria-describedby');
      }
    });
  }
}
