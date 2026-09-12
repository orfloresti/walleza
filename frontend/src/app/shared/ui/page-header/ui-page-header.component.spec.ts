/**
 * `UiPageHeaderComponent` — Phase UI PR4b (task 5.3). The consistent
 * title/action-slot header used by every feature list page. Verifies the
 * title translates through the real `<h1>` and the projected action slot
 * renders alongside it.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiPageHeaderComponent } from './ui-page-header.component';

const TRANSLATIONS = {
  transfers: {
    title: 'Transfers',
  },
};

@Component({
  imports: [UiPageHeaderComponent],
  template: `
    <ui-page-header titleKey="transfers.title">
      <button type="button" data-testid="transfers-create">Add transfer</button>
    </ui-page-header>
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

describe('UiPageHeaderComponent', () => {
  it('renders the translated title in a real <h1>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const h1 = el.querySelector('h1');

    expect(h1?.textContent?.trim()).toBe('Transfers');
  });

  it('projects the action slot alongside the title', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const action = el.querySelector('[data-testid="transfers-create"]');

    expect(action?.textContent?.trim()).toBe('Add transfer');
  });
});
