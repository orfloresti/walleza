/**
 * `UiListCellComponent` — Phase UI PR4b2 (task 5.4/5.5). Renders the real
 * `<div>` (D60) that composes a `md:hidden` mobile label alongside
 * projected content.
 *
 * Task 5.5's regression guard (RED written before the component existed):
 * jsdom does not evaluate media queries, so this suite cannot observe
 * computed visibility at any viewport. It instead asserts the two things
 * that WOULD break if a future edit tried to remove the label from the
 * DOM at desktop widths via a structural conditional (e.g. an `@if` keyed
 * off a breakpoint signal) instead of the CSS-only `md:hidden` class:
 * both the translated label `<span>` and the projected content must
 * always be present in the DOM together, regardless of any assumed
 * viewport, with the visibility responsibility resting entirely on the
 * static `md:hidden` class string.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiListCellComponent } from './ui-list-cell.component';

const TRANSLATIONS = {
  transfers: {
    date: 'Date',
  },
};

@Component({
  imports: [UiListCellComponent],
  template: `
    <ui-list-cell [labelKey]="labelKey">
      <span data-testid="transfer-date">2026-01-15</span>
    </ui-list-cell>
  `,
})
class HostComponent {
  labelKey: string | null = 'transfers.date';
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({
    imports: [
      HostComponent,
      TranslocoTestingModule.forRoot({
        langs: { en: TRANSLATIONS },
        translocoConfig: { availableLangs: ['en'], defaultLang: 'en' },
        preloadLangs: true,
      }),
    ],
  }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiListCellComponent', () => {
  it('always renders the translated md:hidden label span in the DOM (regression guard, task 5.5)', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const label = el.querySelector('span.text-sm.text-on-surface-muted');

    // Markup/class assertion, not computed visibility — jsdom never
    // evaluates the `md:` media query, so `getComputedStyle` cannot tell
    // us anything here. The class list itself is the contract: hiding at
    // desktop widths must stay a CSS concern (`md:hidden`), never a
    // structural one that removes the span from the DOM.
    expect(label).not.toBeNull();
    expect(label?.classList.contains('md:hidden')).toBe(true);
    expect(label?.textContent?.trim()).toBe('Date');
  });

  it('always renders the projected content alongside the label, in the same DOM (regression guard, task 5.5)', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const label = el.querySelector('span.text-sm.text-on-surface-muted');
    const projected = el.querySelector('[data-testid="transfer-date"]');

    expect(label).not.toBeNull();
    expect(projected).not.toBeNull();
    expect(projected?.textContent?.trim()).toBe('2026-01-15');
  });

  it('omits the label span entirely when no labelKey is supplied', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.labelKey = null;
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const label = el.querySelector('span.text-sm.text-on-surface-muted');
    const projected = el.querySelector('[data-testid="transfer-date"]');

    expect(label).toBeNull();
    expect(projected).not.toBeNull();
  });
});
