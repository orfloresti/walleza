import { Component, computed, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import { FOCUS_RING } from '../ui-classes';

export type UiButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
export type UiButtonSize = 'sm' | 'md';

const VARIANT_CLASSES: Record<UiButtonVariant, string> = {
  primary: 'bg-primary text-on-primary hover:opacity-90',
  secondary: 'bg-surface-variant text-on-surface border border-border hover:opacity-90',
  danger: 'bg-danger text-on-danger hover:opacity-90',
  ghost: 'bg-transparent text-on-surface hover:bg-surface-variant',
};

const SIZE_CLASSES: Record<UiButtonSize, string> = {
  sm: 'px-2.5 py-1.5 text-sm',
  md: 'px-4 py-2 text-base',
};

/**
 * Design D57/D58/D63 — a real `<button>` (or `<a routerLink>` when `link`
 * is set), never a wrapper or a host-level attribute. `data-testid` and
 * every native attribute forward onto that inner element so existing page
 * specs (`querySelectorAll('button')` + `.click()`) keep working unchanged.
 *
 * No `clicked` output on purpose: a native click on the inner `<button>`
 * bubbles to the `<ui-button>` host, where the page's own
 * `(click)="…"` binding fires exactly as it does on a plain `<button>`
 * today. Forcing every call site to rename `(click)` would buy nothing.
 */
@Component({
  selector: 'ui-button',
  imports: [RouterLink],
  templateUrl: './ui-button.component.html',
})
export class UiButtonComponent {
  readonly variant = input<UiButtonVariant>('secondary');
  readonly size = input<UiButtonSize>('md');
  readonly block = input(false);
  readonly type = input<'button' | 'submit'>('button');
  readonly disabled = input(false);
  readonly link = input<string | null>(null);
  readonly testId = input<string | null>(null);

  protected readonly classes = computed(() => {
    const parts = [VARIANT_CLASSES[this.variant()], SIZE_CLASSES[this.size()], FOCUS_RING];
    if (this.block()) {
      parts.push('w-full');
    }
    return parts.join(' ');
  });
}
