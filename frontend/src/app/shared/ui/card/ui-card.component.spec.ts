/**
 * `UiCardComponent` — Phase UI PR4a (task 4.1). A structural container
 * with no variant surface: verifies `testId` forwards onto the real
 * `<section>` (D58) and projected content renders inside it.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiCardComponent } from './ui-card.component';

@Component({
  imports: [UiCardComponent],
  template: `
    <ui-card testId="workspace-summary">
      <p data-testid="summary-body">Summary content</p>
    </ui-card>
  `,
})
class HostComponent {}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiCardComponent', () => {
  it('renders the testid on the real native <section>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const section = el.querySelector('[data-testid="workspace-summary"]');

    expect(section).not.toBeNull();
    expect(section?.tagName).toBe('SECTION');
  });

  it('projects its content inside the section', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const section = el.querySelector('[data-testid="workspace-summary"]');
    const body = section?.querySelector('[data-testid="summary-body"]');

    expect(body?.textContent?.trim()).toBe('Summary content');
  });
});
