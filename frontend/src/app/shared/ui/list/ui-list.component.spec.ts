/**
 * `UiListComponent` — Phase UI PR4b2 (task 5.4). Renders the real `<ul>`
 * (D58, D60) that hosts `ui-list-row` children. Verifies `testId`
 * forwards onto that native element and projected rows render inside it.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { UiListComponent } from './ui-list.component';

@Component({
  imports: [UiListComponent],
  template: `
    <ui-list testId="transfers-list">
      <li data-testid="transfers-list-row">Row content</li>
    </ui-list>
  `,
})
class HostComponent {}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiListComponent', () => {
  it('renders the testid on the real native <ul>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const ul = el.querySelector('[data-testid="transfers-list"]');

    expect(ul).not.toBeNull();
    expect(ul?.tagName).toBe('UL');
  });

  it('projects row content inside the <ul>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const ul = el.querySelector('[data-testid="transfers-list"]');
    const row = ul?.querySelector('[data-testid="transfers-list-row"]');

    expect(row?.textContent?.trim()).toBe('Row content');
  });
});
