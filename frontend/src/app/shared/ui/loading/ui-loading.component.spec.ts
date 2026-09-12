/**
 * `UiLoadingComponent` — Phase UI PR4b (task 5.2). A live-region status
 * message shown while a list request is in flight, structurally distinct
 * from the empty state and error alert (D64). Verifies `testId` forwards
 * onto the real `<p role="status">` (D58) and the message translates.
 */
import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiLoadingComponent } from './ui-loading.component';

const TRANSLATIONS = {
  transfers: {
    loading: 'Loading transfers…',
  },
};

@Component({
  imports: [UiLoadingComponent],
  template: `<ui-loading testId="transfers-loading" messageKey="transfers.loading" />`,
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

describe('UiLoadingComponent', () => {
  it('renders role="status" and the testid on the real native <p>', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const p = el.querySelector('[data-testid="transfers-loading"]');

    expect(p).not.toBeNull();
    expect(p?.tagName).toBe('P');
    expect(p?.getAttribute('role')).toBe('status');
  });

  it('renders the translated message', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const p = el.querySelector('[data-testid="transfers-loading"]');

    expect(p?.textContent?.trim()).toBe('Loading transfers…');
  });
});
