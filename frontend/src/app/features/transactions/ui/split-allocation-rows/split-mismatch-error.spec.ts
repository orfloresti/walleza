/**
 * Unit tests for `parseSplitMismatchError` against the two EXACT message
 * shapes `backend/app/transactions/service.py` actually raises (read
 * directly from its source, not assumed) — see the module doc comment
 * for why this deviates from design D33's literal `expected_total`/
 * `allocated_total` JSON-field wording.
 */
import { describe, expect, it } from 'vitest';

import { parseSplitMismatchError } from './split-mismatch-error';

describe('parseSplitMismatchError', () => {
  it('extracts allocated (got) and expected totals from the create-path message (task focus)', () => {
    const result = parseSplitMismatchError(
      'split amounts must sum exactly to the transaction amount (got 90.00, expected 100.00)',
    );

    expect(result).not.toBeNull();
    expect(result?.allocatedTotal).toBe('90.00');
    expect(result?.expectedTotal).toBe('100.00');
    expect(result?.rawMessage).toContain('90.00');
    expect(result?.rawMessage).toContain('100.00');
  });

  it('extracts allocated (existing) and expected totals from the update-amount-without-splits message (task focus)', () => {
    const result = parseSplitMismatchError(
      'existing splits (90.00) no longer sum to the updated transaction amount (100.00); update splits too',
    );

    expect(result).not.toBeNull();
    expect(result?.allocatedTotal).toBe('90.00');
    expect(result?.expectedTotal).toBe('100.00');
  });

  it('never computes or re-derives the numbers — only substrings already present in the server message', () => {
    const result = parseSplitMismatchError(
      'split amounts must sum exactly to the transaction amount (got 3.33, expected 10.00)',
    );

    // 3.33 * 3 = 9.99, not 10.00 — a client that "helpfully" recomputed
    // would be tempted to report 9.99. Assert the server's own numbers
    // pass through completely untouched.
    expect(result?.allocatedTotal).toBe('3.33');
    expect(result?.expectedTotal).toBe('10.00');
  });

  it('returns a rawMessage-only result when a split-related detail names fewer than two numbers', () => {
    const result = parseSplitMismatchError(
      'one or more split categories are not visible in this workspace',
    );

    expect(result).not.toBeNull();
    expect(result?.rawMessage).toBe(
      'one or more split categories are not visible in this workspace',
    );
    expect(result?.expectedTotal).toBeNull();
    expect(result?.allocatedTotal).toBeNull();
  });

  it('returns null for a non-split validation error', () => {
    expect(parseSplitMismatchError('account not found')).toBeNull();
  });

  it('returns null for a non-string detail', () => {
    expect(parseSplitMismatchError(undefined)).toBeNull();
    expect(parseSplitMismatchError({ some: 'object' })).toBeNull();
  });
});
