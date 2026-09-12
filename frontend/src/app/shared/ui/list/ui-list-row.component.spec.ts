/**
 * `UiListRowComponent` — Phase UI PR4b2 (task 5.4). Renders the real
 * `<li>` (D60) that composes `ui-list-cell` children. No `data-testid`
 * or other inputs — no spec migrated by this phase selects a row by
 * testid or tag. Verifies projected cell content renders inside it.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiListRowComponent } from './ui-list-row.component';

@Component({
  imports: [UiListRowComponent],
  template: `
    <ui-list-row>
      <span data-testid="transfer-from">Checking</span>
    </ui-list-row>
  `,
})
class HostComponent {}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiListRowComponent', () => {
  it('renders a real native <li>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const li = el.querySelector('li');

    expect(li).not.toBeNull();
  });

  it('projects cell content inside the <li>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const li = el.querySelector('li');
    const cell = li?.querySelector('[data-testid="transfer-from"]');

    expect(cell?.textContent?.trim()).toBe('Checking');
  });
});
