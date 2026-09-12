/**
 * `UiEmptyStateComponent` — Phase UI PR4b (task 5.1). The third,
 * structurally separate branch a list page renders on a successful load
 * with zero items (D64). Verifies `testId` forwards onto the real `<div>`
 * (D58), title/message translate through transloco, and projected action
 * content renders inside it.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiEmptyStateComponent } from './ui-empty-state.component';

const TRANSLATIONS = {
  transfers: {
    empty: {
      title: 'No transfers yet',
      body: 'Create your first transfer to see it here.',
    },
  },
};

@Component({
  imports: [UiEmptyStateComponent],
  template: `
    <ui-empty-state testId="transfers-empty" titleKey="transfers.empty.title" messageKey="transfers.empty.body">
      <button type="button" data-testid="transfers-empty-action">Add transfer</button>
    </ui-empty-state>
  `,
})
class HostComponent {}

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

describe('UiEmptyStateComponent', () => {
  it('renders the testid on the real native <div>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const div = el.querySelector('[data-testid="transfers-empty"]');

    expect(div).not.toBeNull();
    expect(div?.tagName).toBe('DIV');
  });

  it('renders the translated title and message', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No transfers yet');
    expect(el.textContent).toContain('Create your first transfer to see it here.');
  });

  it('projects the action content inside the empty state', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const action = el.querySelector('[data-testid="transfers-empty-action"]');

    expect(action?.textContent?.trim()).toBe('Add transfer');
  });
});
