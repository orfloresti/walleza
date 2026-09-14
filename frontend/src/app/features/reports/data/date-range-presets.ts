/**
 * Client-side preset-to-date-range resolution (design D89): the page
 * resolves a preset into concrete `date_from`/`date_to` BEFORE calling the
 * API, which only ever receives resolved dates — there is no preset enum
 * on the wire (design D88's route table). A pure, testable function, kept
 * independent of Angular so it can be unit-tested with plain `Date`s.
 */

export type DateRangePreset = 'this_month' | 'last_3_months' | 'year_to_date' | 'custom';

export interface ResolvedDateRange {
  date_from: string;
  date_to: string;
}

function toIsoDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** Resolves every non-`custom` preset relative to `today`. Returns `null`
 * for `custom` — the caller is responsible for supplying its own
 * `date_from`/`date_to` (from the custom-range inputs) in that case. */
export function resolvePreset(preset: DateRangePreset, today: Date): ResolvedDateRange | null {
  switch (preset) {
    case 'this_month': {
      const from = new Date(today.getFullYear(), today.getMonth(), 1);
      const to = new Date(today.getFullYear(), today.getMonth() + 1, 0);
      return { date_from: toIsoDate(from), date_to: toIsoDate(to) };
    }
    case 'last_3_months': {
      const from = new Date(today.getFullYear(), today.getMonth() - 2, 1);
      const to = new Date(today.getFullYear(), today.getMonth() + 1, 0);
      return { date_from: toIsoDate(from), date_to: toIsoDate(to) };
    }
    case 'year_to_date': {
      const from = new Date(today.getFullYear(), 0, 1);
      return { date_from: toIsoDate(from), date_to: toIsoDate(today) };
    }
    case 'custom':
      return null;
  }
}
