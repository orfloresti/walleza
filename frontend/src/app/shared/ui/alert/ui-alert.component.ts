import { Component, computed, effect, input, isDevMode } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

export type UiAlertVariant = 'error' | 'warning' | 'info';

const BASE_CLASSES = 'rounded-lg px-3 py-2 text-sm';

/**
 * Design D57/D59/D63 — the phase's security-sensitive component. `messageKey`
 * and `message` render through two STRUCTURALLY SEPARATE template branches
 * (see `ui-alert.component.html`), never one branch with a conditional
 * pipe expression. The verbatim (`message`) branch contains ZERO pipes
 * anywhere in its render path, so a server 422 `detail` — even one that
 * happens to be shaped like a valid transloco key (e.g. "errors.required")
 * — can never reach `| transloco` regardless of its content. Do not merge
 * the two branches and do not add a pipe to the verbatim branch: doing so
 * would compile and pass every test that only checks translated output,
 * while silently letting server/attacker-controlled text be treated as a
 * translation lookup key.
 *
 * `messageKey` and `message` are mutually exclusive. Setting both throws
 * in dev mode via a constructor `effect()`, converting a silent precedence
 * rule into a failing spec rather than an unnoticed runtime ambiguity.
 *
 * `role` mirrors what each severity already renders today: `error`/
 * `warning` get `role="alert"`, `info` gets no role at all (e.g.
 * `transfers-balance-notice` is a plain `<p>` with no role today).
 */
const VARIANT_CLASSES: Record<UiAlertVariant, string> = {
  error: 'border border-danger/40 bg-danger/10 text-on-surface',
  warning: 'border border-warning/40 bg-warning/10 text-on-surface',
  info: 'border border-border bg-surface-variant text-on-surface',
};

@Component({
  selector: 'ui-alert',
  imports: [TranslocoPipe],
  templateUrl: './ui-alert.component.html',
})
export class UiAlertComponent {
  readonly variant = input<UiAlertVariant>('error');
  readonly messageKey = input<string | null>(null);
  readonly message = input<string | null>(null);
  readonly testId = input<string | null>(null);

  protected readonly role = computed(() => (this.variant() === 'info' ? null : 'alert'));
  protected readonly classes = computed(
    () => `${BASE_CLASSES} ${VARIANT_CLASSES[this.variant()]}`,
  );

  constructor() {
    effect(() => {
      if (isDevMode() && this.messageKey() !== null && this.message() !== null) {
        throw new Error('ui-alert: `messageKey` and `message` are mutually exclusive.');
      }
    });
  }
}
