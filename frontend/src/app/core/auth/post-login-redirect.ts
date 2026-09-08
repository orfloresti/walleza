/**
 * Preserves a deep link across the full-page navigation to the
 * backend-driven Google OAuth flow (design's Phase 1 frontend routing
 * note). Phase 0's `/api/auth/callback` redirects to a hardcoded `/`,
 * which would otherwise drop a guarded destination such as
 * `/join/:token` — `AuthService.redirectToLogin()` is a
 * `window.location.href` navigation, not an Angular router navigation,
 * so no in-memory route state survives it.
 *
 * `sessionStorage` (not `localStorage`) is deliberate: the stash is only
 * ever meaningful for the single in-flight login round trip in this
 * browser tab, not a durable cross-session preference (mirrors the
 * reasoning `LanguageService` documents for choosing `localStorage` for
 * its own, differently-scoped, persisted choice).
 */
const STORAGE_KEY = 'walleza.postLoginRedirect';

/** Called by `authGuard` right before it redirects an unauthenticated
 * visitor away — stores the URL that was blocked so it can be replayed
 * once the session is established. No-op for an empty/falsy URL. */
export function stashPostLoginRedirect(url: string | undefined | null): void {
  if (!url) {
    return;
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, url);
  } catch {
    // sessionStorage can be unavailable (private browsing, disabled
    // storage); the redirect simply won't survive the round trip.
  }
}

/** Called by `authGuard` once a navigation is authenticated — returns
 * and clears the stashed URL, if any, so it is consumed exactly once. */
export function consumePostLoginRedirect(): string | null {
  try {
    const url = sessionStorage.getItem(STORAGE_KEY);
    if (url) {
      sessionStorage.removeItem(STORAGE_KEY);
    }
    return url;
  } catch {
    return null;
  }
}
