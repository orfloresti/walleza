/**
 * `UiAlertComponent` — Phase UI PR4a2 (tasks 4.3-4.6). Written RED-first,
 * before `ui-alert.component.ts`/`.html` exist (task 4.7). This is the
 * phase's security-sensitive component (design D59): a server 422
 * `detail` must never reach the `| transloco` pipe, even when its content
 * happens to be shaped exactly like a valid transloco key. The
 * `TRANSLATIONS` fixture below deliberately defines a translation for
 * `transfers.balanceNotice` — the same string used as a raw `message` in
 * task 4.4 — so that if the verbatim branch were ever merged with the
 * translated branch (or a pipe were added to it), this spec would render
 * the TRANSLATED text instead of the literal key string and fail.
 */
import { Component, isDevMode } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { describe, expect, it } from 'vitest';

import { UiAlertComponent, UiAlertVariant } from './ui-alert.component';

const TRANSLATIONS = {
  transfers: {
    // Deliberately colliding key: identical to the raw string used as
    // `message` in the "verbatim, even if key-shaped" test below. If the
    // verbatim branch ever became reachable by `| transloco`, this test
    // would render this translation instead of the literal key.
    balanceNotice: 'Transfers are recorded here but do not yet change any account balance.',
  },
};

@Component({
  imports: [UiAlertComponent],
  template: `
    <ui-alert
      [variant]="variant"
      [messageKey]="messageKey"
      [message]="message"
      testId="alert-under-test"
    />
  `,
})
class HostComponent {
  variant: UiAlertVariant = 'error';
  messageKey: string | null = null;
  message: string | null = null;
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

describe('UiAlertComponent', () => {
  it('renders messageKey translated through | transloco (task 4.3)', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.messageKey = 'transfers.balanceNotice';
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const alert = el.querySelector('[data-testid="alert-under-test"]');

    expect(alert?.textContent?.trim()).toBe(
      'Transfers are recorded here but do not yet change any account balance.',
    );
  });

  it(
    'renders a key-shaped `message` string LITERALLY, unchanged, with no transloco ' +
      'lookup applied — proves the verbatim branch cannot translate even key-shaped ' +
      'input (task 4.4)',
    async () => {
      const fixture = await createFixture();
      fixture.componentInstance.message = 'transfers.balanceNotice';
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const alert = el.querySelector('[data-testid="alert-under-test"]');

      expect(alert?.textContent?.trim()).toBe('transfers.balanceNotice');
    },
  );

  it('throws when both messageKey and message are set simultaneously, under isDevMode() (task 4.5)', async () => {
    expect(isDevMode()).toBe(true);

    const fixture = await createFixture();
    fixture.componentInstance.messageKey = 'transfers.balanceNotice';
    fixture.componentInstance.message = 'raw server detail';

    expect(() => fixture.detectChanges()).toThrow(
      /messageKey.*message.*mutually exclusive/i,
    );
  });

  it('variant="info" renders no role attribute (task 4.6)', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.variant = 'info';
    fixture.componentInstance.messageKey = 'transfers.balanceNotice';
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const alert = el.querySelector('[data-testid="alert-under-test"]');

    expect(alert?.hasAttribute('role')).toBe(false);
  });

  for (const variant of ['error', 'warning'] as const) {
    it(`variant="${variant}" renders role="alert" (task 4.6)`, async () => {
      const fixture = await createFixture();
      fixture.componentInstance.variant = variant;
      fixture.componentInstance.messageKey = 'transfers.balanceNotice';
      fixture.detectChanges();

      const el = fixture.nativeElement as HTMLElement;
      const alert = el.querySelector('[data-testid="alert-under-test"]');

      expect(alert?.getAttribute('role')).toBe('alert');
    });
  }

  it('forwards testId onto the real native <p> in the messageKey branch (D58)', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.messageKey = 'transfers.balanceNotice';
    fixture.detectChanges();
    const alert = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="alert-under-test"]',
    );
    expect(alert?.tagName).toBe('P');
  });

  it('forwards testId onto the real native <p> in the message (verbatim) branch (D58)', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.message = 'raw server detail';
    fixture.detectChanges();
    const alert = (fixture.nativeElement as HTMLElement).querySelector(
      '[data-testid="alert-under-test"]',
    );
    expect(alert?.tagName).toBe('P');
  });
});
