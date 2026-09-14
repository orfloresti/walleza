import { Component, computed, input } from '@angular/core';

export type UiBadgeVariant =
  | 'personal'
  | 'archived'
  | 'refund'
  | 'checked'
  | 'subscription'
  | 'on_track'
  | 'near_limit'
  | 'over_budget';

const BASE_CLASSES = 'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium';

/**
 * Design D57/D63, spec `design-system` (ui-badge Semantic Variant Set) —
 * the original 5 named variants, each mapped to a semantic token, never a
 * hardcoded color. `archived` uses `--on-surface-muted`/`--border`
 * (spec's stated assumption: no dedicated neutral-badge token exists).
 * Class strings are complete literals per D63 — Tailwind's source scanner
 * needs every class name to appear verbatim, so this map is never
 * template-interpolated.
 *
 * Phase 5 (Budgets, design D75) extends the set with `on_track`/
 * `near_limit`/`over_budget`, reusing the same 3 semantic tokens the kit
 * already exposes (`--success`/`--warning`/`--danger`, the latter two
 * already used by `ui-alert`'s `warning`/`error` variants) rather than
 * introducing new ones.
 */
const VARIANT_CLASSES: Record<UiBadgeVariant, string> = {
  personal: 'bg-primary text-on-primary',
  archived: 'border border-border text-on-surface-muted',
  refund: 'bg-danger text-on-danger',
  checked: 'bg-success text-on-success',
  subscription: 'bg-primary text-on-primary',
  on_track: 'bg-success text-on-success',
  near_limit: 'bg-warning text-on-warning',
  over_budget: 'bg-danger text-on-danger',
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
