/**
 * Shared Tailwind class fragments for `shared/ui/` kit components (design
 * D63). Kept as complete literal strings — never template-interpolated —
 * so Tailwind v4's source scanner can always see them and every kit
 * component that needs the same visual behavior references one place
 * instead of retyping the utility list.
 */

/** Visible keyboard-focus ring, token-driven (`outline-primary`), applied
 * to every interactive kit element (button, native form controls). */
export const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary';

/** Standard color/opacity transition for interactive elements. */
export const TRANSITION_COLORS = 'transition-colors';

/** Disabled-state treatment shared by buttons and native form controls. */
export const DISABLED_STATE = 'disabled:opacity-50 disabled:pointer-events-none';
