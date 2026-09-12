/**
 * `UiBadgeComponent` — Phase UI PR4a (task 4.2). Written RED-first:
 * asserts each of the 5 spec-mandated variants (`personal`, `archived`,
 * `refund`, `checked`, `subscription`) resolves its color from a semantic
 * token class, never a hardcoded color, and that `testId` forwards onto
 * the real `<span>` (D58). `archived` uses `--on-surface-muted`/`--border`
 * per the spec's stated assumption (no dedicated neutral-badge token).
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiBadgeComponent, UiBadgeVariant } from './ui-badge.component';

@Component({
  imports: [UiBadgeComponent],
  template: `<ui-badge [variant]="variant" testId="row-badge">{{ label }}</ui-badge>`,
})
class HostComponent {
  variant: UiBadgeVariant = 'personal';
  label = 'Personal';
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

const EXPECTED_TOKEN_CLASSES: Record<UiBadgeVariant, string[]> = {
  personal: ['bg-primary', 'text-on-primary'],
  archived: ['text-on-surface-muted', 'border-border'],
  refund: ['bg-danger', 'text-on-danger'],
  checked: ['bg-success', 'text-on-success'],
  subscription: ['bg-primary', 'text-on-primary'],
};

describe('UiBadgeComponent', () => {
  it('renders the testid on the real native <span>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const span = el.querySelector('[data-testid="row-badge"]');

    expect(span).not.toBeNull();
    expect(span?.tagName).toBe('SPAN');
  });

  for (const variant of Object.keys(EXPECTED_TOKEN_CLASSES) as UiBadgeVariant[]) {
    it(`variant="${variant}" resolves its color from a semantic token, not a hardcoded value`, async () => {
      const fixture = await createFixture();
      fixture.componentInstance.variant = variant;
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const span = el.querySelector('[data-testid="row-badge"]') as HTMLElement;

      for (const tokenClass of EXPECTED_TOKEN_CLASSES[variant]) {
        expect(span.className).toContain(tokenClass);
      }
      expect(span.getAttribute('style')).toBeNull();
    });
  }
});
