/**
 * Spec `internationalization`:
 * - "Default locale on first load" — resolution order is stored choice,
 *   then a supported `navigator.language` match, then the `en` default.
 * - "Switching locale updates strings" — proven end to end here against
 *   a real `TranslocoPipe` render, using `TranslocoTestingModule` (no
 *   network) with the same proof-string pair shipped in
 *   `frontend/public/i18n/{en,es}.json`.
 */

import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { TranslocoPipe, TranslocoTestingModule } from '@jsverse/transloco';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LanguageService } from './language.service';

const PROOF_STRINGS = {
  en: { home: { greeting: 'Welcome to Walleza' } },
  es: { home: { greeting: 'Bienvenido a Walleza' } },
};

@Component({
  imports: [TranslocoPipe],
  template: `{{ 'home.greeting' | transloco }}`,
})
class ProofStringHostComponent {}

function setNavigatorLanguage(lang: string): void {
  Object.defineProperty(window.navigator, 'language', {
    value: lang,
    configurable: true,
  });
}

describe('LanguageService', () => {
  const originalLanguageDescriptor = Object.getOwnPropertyDescriptor(
    window.navigator,
    'language',
  );

  beforeEach(() => {
    localStorage.removeItem('walleza.lang');
    TestBed.configureTestingModule({
      imports: [
        TranslocoTestingModule.forRoot({
          langs: PROOF_STRINGS,
          translocoConfig: {
            availableLangs: ['en', 'es'],
            defaultLang: 'en',
            reRenderOnLangChange: true,
          },
          preloadLangs: true,
        }),
      ],
    });
  });

  afterEach(() => {
    localStorage.removeItem('walleza.lang');
    if (originalLanguageDescriptor) {
      Object.defineProperty(window.navigator, 'language', originalLanguageDescriptor);
    }
  });

  it('defaults to en when there is no stored preference and navigator.language is unsupported', () => {
    setNavigatorLanguage('fr-FR');
    const service = TestBed.inject(LanguageService);

    expect(service.resolveInitialLang()).toBe('en');
  });

  it('derives the default locale from a supported navigator.language', () => {
    setNavigatorLanguage('es-MX');
    const service = TestBed.inject(LanguageService);

    expect(service.resolveInitialLang()).toBe('es');
  });

  it('prefers a stored localStorage choice over navigator.language', () => {
    setNavigatorLanguage('es-MX');
    localStorage.setItem('walleza.lang', 'en');
    const service = TestBed.inject(LanguageService);

    expect(service.resolveInitialLang()).toBe('en');
  });

  it('persists the choice made via setLang', () => {
    const service = TestBed.inject(LanguageService);

    service.setLang('es');

    expect(localStorage.getItem('walleza.lang')).toBe('es');
  });

  it('updates a rendered proof string when the locale is switched at runtime', async () => {
    const service = TestBed.inject(LanguageService);

    service.setLang('es');
    const fixture: ComponentFixture<ProofStringHostComponent> =
      TestBed.createComponent(ProofStringHostComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent?.trim()).toBe(
      'Bienvenido a Walleza',
    );

    service.setLang('en');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent?.trim()).toBe(
      'Welcome to Walleza',
    );
  });
});
