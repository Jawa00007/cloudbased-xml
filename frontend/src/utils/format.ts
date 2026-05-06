/**
 * Format a number with Italian locale: comma decimal separator, period thousands.
 * e.g. 2595.451 → "2.595,451"
 */
export function itNum(
  n: number | null | undefined,
  opts: Intl.NumberFormatOptions = {},
): string {
  if (n == null) return '—'
  return n.toLocaleString('it-IT', opts)
}

/** Format kWh with up to 3 decimal places */
export function itKwh(n: number | null | undefined): string {
  return itNum(n, { maximumFractionDigits: 3 })
}

/** Format MWh with up to 4 decimal places */
export function itMwh(n: number | null | undefined): string {
  return itNum(n, { maximumFractionDigits: 4 })
}

/** Format a percentage (0–100) with 2 decimal places */
export function itPct(n: number | null | undefined): string {
  return itNum(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
