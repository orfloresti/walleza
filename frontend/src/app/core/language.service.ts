import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { TranslocoLoader, TranslocoService, Translation } from '@jsverse/transloco';
import { Observable } from 'rxjs';

/** Locales supported by the Phase 0 i18n scaffold (spec `internationalization`). */
export const SUPPORTED_LANGS = ['en', 'es'] as const;
export type SupportedLang = (typeof SUPPORTED_LANGS)[number];
/** Fallback locale when neither a stored choice nor `navigator.language` match. */
export const DEFAULT_LANG: SupportedLang = 'en';

const STORAGE_KEY = 'walleza.lang';

/**
 * Fetches runtime translation JSON from `frontend/public/i18n/{lang}.json`
 * (design D4 — one deploy artifact, in-place locale switching rather than
 * a build-per-locale). The service worker MUST precache these files or the
 * offline shell falls back to raw translation keys (design D6a).
 */
@Injectable({ providedIn: 'root' })
export class TranslocoHttpLoader implements TranslocoLoader {
  private readonly http = inject(HttpClient);

  getTranslation(lang: string): Observable<Translation> {
    return this.http.get<Translation>(`/i18n/${lang}.json`);
  }
}

/**
 * Owns the active-locale lifecycle (spec `internationalization`). Resolution
 * order on first load: a previously persisted `localStorage:walleza.lang`
 * choice, then a supported match against `navigator.language`, then the
 * `en` default (design D4).
 */
@Injectable({ providedIn: 'root' })
export class LanguageService {
  private readonly transloco = inject(TranslocoService);

  /** Applies the resolved initial language to Transloco. Call once at bootstrap. */
  init(): void {
    this.setLang(this.resolveInitialLang());
  }

  /** Switches the active locale at runtime and persists the choice. */
  setLang(lang: SupportedLang): void {
    this.transloco.setActiveLang(lang);
    this.persist(lang);
  }

  /** The locale that would be applied on a fresh load, without side effects. */
  resolveInitialLang(): SupportedLang {
    return this.readStoredLang() ?? this.matchSupportedLang(navigator.language) ?? DEFAULT_LANG;
  }

  private persist(lang: SupportedLang): void {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // localStorage can be unavailable (private browsing, disabled storage);
      // the runtime locale still switches, only persistence is skipped.
    }
  }

  private readStoredLang(): SupportedLang | null {
    try {
      return this.toSupportedLang(localStorage.getItem(STORAGE_KEY));
    } catch {
      return null;
    }
  }

  private matchSupportedLang(navigatorLang: string): SupportedLang | null {
    return this.toSupportedLang(navigatorLang.slice(0, 2).toLowerCase());
  }

  private toSupportedLang(value: string | null): SupportedLang | null {
    return value && (SUPPORTED_LANGS as readonly string[]).includes(value)
      ? (value as SupportedLang)
      : null;
  }
}
