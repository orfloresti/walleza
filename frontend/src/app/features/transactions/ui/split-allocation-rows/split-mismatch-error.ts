/**
 * Design D33 says a split-sum mismatch returns 422 with `expected_total`
 * and `allocated_total` as strings, which the form renders verbatim — no
 * client-side arithmetic.
 *
 * The ACTUALLY SHIPPED backend (`app/transactions/service.py`'s
 * `TransactionSplitValidationError`, wired to 422 by
 * `app/transactions/router.py`, PR3b — already independently verified
 * PASS) does NOT return a structured `{expected_total, allocated_total}`
 * JSON body. It returns a single prose `detail` string with both numbers
 * embedded, in one of two exact forms depending on which check failed:
 *
 *   create / explicit-splits-on-update:
 *     "split amounts must sum exactly to the transaction amount
 *      (got 90.00, expected 100.00)"
 *
 *   amount-changed-without-touching-splits on update:
 *     "existing splits (90.00) no longer sum to the updated transaction
 *      amount (100.00); update splits too"
 *
 * In BOTH forms the first decimal number that appears is the ALLOCATED
 * total (what the split lines currently/actually sum to — "got" or
 * "existing splits") and the second is the EXPECTED total (the
 * transaction's own amount) — read directly from `service.py`'s two
 * f-strings, not assumed. This parser never computes, sums, or
 * re-derives either number: it only extracts substrings the server
 * itself already wrote, which keeps the server as the sole arithmetic
 * authority (design D33's actual intent), even though the transport
 * shape here is prose, not a dedicated JSON field pair.
 *
 * This is a genuine deviation from design D33's literal wording,
 * driven by the real, already-verified backend contract — flagged in
 * this PR's apply-progress/return summary, not silently patched over.
 */
export interface SplitMismatchError {
  /** The server's own `detail` string, untouched, always safe to render
   * as a fallback. */
  rawMessage: string;
  /** The transaction's own (target) amount, extracted from `rawMessage`.
   * `null` when exactly two decimal numbers could not be confidently
   * found — the caller then falls back to `rawMessage` alone. */
  expectedTotal: string | null;
  /** What the split lines currently/actually sum to, extracted from
   * `rawMessage`. `null` under the same condition as `expectedTotal`. */
  allocatedTotal: string | null;
}

const DECIMAL_NUMBER = /-?\d+\.\d+/g;

/**
 * Parses a `TransactionSplitValidationError`'s 422 `detail` string (see
 * module doc) into `{ expectedTotal, allocatedTotal }`. Returns `null`
 * when `detail` is not a split-sum-mismatch message at all (e.g. the
 * cross-workspace-category or duplicate-category-in-split
 * `TransactionSplitValidationError` messages, which name no totals, or a
 * completely different 422 such as an invalid `account_id`) — callers
 * MUST fall back to a generic validation-error message in that case.
 */
export function parseSplitMismatchError(detail: unknown): SplitMismatchError | null {
  if (typeof detail !== 'string') {
    return null;
  }
  if (!detail.toLowerCase().includes('split')) {
    return null;
  }

  const numbers = detail.match(DECIMAL_NUMBER);
  if (!numbers || numbers.length < 2) {
    return { rawMessage: detail, expectedTotal: null, allocatedTotal: null };
  }

  return {
    rawMessage: detail,
    allocatedTotal: numbers[0],
    expectedTotal: numbers[1],
  };
}
