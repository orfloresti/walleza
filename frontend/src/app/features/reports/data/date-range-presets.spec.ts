import { describe, expect, it } from 'vitest';

import { resolvePreset } from './date-range-presets';

describe('resolvePreset', () => {
  const today = new Date(2026, 8, 14); // 2026-09-14 (month is 0-indexed)

  it('this_month resolves to the first/last day of the current month', () => {
    expect(resolvePreset('this_month', today)).toEqual({
      date_from: '2026-09-01',
      date_to: '2026-09-30',
    });
  });

  it('last_3_months resolves to the first day 2 months back through today\'s month end', () => {
    expect(resolvePreset('last_3_months', today)).toEqual({
      date_from: '2026-07-01',
      date_to: '2026-09-30',
    });
  });

  it('last_3_months rolls back across a year boundary', () => {
    const januaryToday = new Date(2026, 0, 15); // 2026-01-15
    expect(resolvePreset('last_3_months', januaryToday)).toEqual({
      date_from: '2025-11-01',
      date_to: '2026-01-31',
    });
  });

  it('year_to_date resolves from Jan 1 of the current year through today', () => {
    expect(resolvePreset('year_to_date', today)).toEqual({
      date_from: '2026-01-01',
      date_to: '2026-09-14',
    });
  });

  it('custom returns null — the caller supplies its own range', () => {
    expect(resolvePreset('custom', today)).toBeNull();
  });
});
