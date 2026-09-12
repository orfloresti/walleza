import { Component, computed, input } from '@angular/core';

export type UiBadgeVariant = 'personal' | 'archived' | 'refund' | 'checked' | 'subscription';

const BASE_CLASSES = 'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium';

/**
 * Design D57/D63, spec `design-system` (ui-badge Semantic Variant Set) —
 * exactly the 5 named variants, each mapped to a semantic token, never a
 * hardcoded color. `archived` uses `--on-surface-muted`/`--border`
 * (spec's stated assumption: no dedicated neutral-badge token exists).
 * Class strings are complete literals per D63 — Tailwind's source scanner
 * needs every class name to appear verbatim, so this map is never
 * template-interpolated.
 */
const VARIANT_CLASSES: Record<UiBadgeVariant, string> = {
  personal: 'bg-primary text-on-primary',
  archived: 'border border-border text-on-surface-muted',
  refund: 'bg-danger text-on-danger',
  checked: 'bg-success text-on-success',
  subscription: 'bg-primary text-on-primary',
};

@Component({
  selector: 'ui-badge',
  templateUrl: './ui-badge.component.html',
})
export class UiBadgeComponent {
  readonly variant = input.required<UiBadgeVariant>();
  readonly testId = input<string | null>(null);

  protected readonly classes = computed(() => `${BASE_CLASSES} ${VARIANT_CLASSES[this.variant()]}`);
}
