/**
 * Display formatting (en-IN, ₹, lakh grouping). Money arrives as decimal strings and is
 * formatted as text: the browser never does arithmetic on it (ADR-0008). M4 adds the compact
 * forms (₹50K / ₹1L / ₹2Cr).
 */

/** "1234567.5" → "12,34,567.50" */
export function groupIndian(decimal: string): string {
  const negative = decimal.trim().startsWith('-')
  const [wholeRaw = '0', fracRaw = ''] = decimal.trim().replace(/^[-+]/, '').split('.')
  const whole = wholeRaw.replace(/^0+(?=\d)/, '')
  const frac = (fracRaw + '00').slice(0, 2)
  let grouped = whole
  if (whole.length > 3) {
    const head = whole.slice(0, -3)
    const tail = whole.slice(-3)
    grouped = `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ',')},${tail}`
  }
  return `${negative ? '-' : ''}${grouped}.${frac}`
}

/** "2350" → "₹2,350.00"; negative values use a real minus sign. */
export function formatMoney(decimal: string | null | undefined): string {
  if (decimal === null || decimal === undefined || decimal === '') return '—'
  const grouped = groupIndian(decimal)
  return grouped.startsWith('-') ? `−₹${grouped.slice(1)}` : `₹${grouped}`
}

const DATE = new Intl.DateTimeFormat('en-IN', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

/** "2026-09-05" → "5 Sept 2026" (the browser's en-IN month abbreviation). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return iso
  return DATE.format(new Date(Date.UTC(y, m - 1, d)))
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ------------------------------------------------------------------ dashboard formats (M4)

const MINUS = '−'
const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

/** Add one to a string of digits ("999" → "1000"), without converting to a number. */
function incrementDigits(digits: string): string {
  const out = digits.split('')
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i] !== '9') {
      out[i] = String(Number(out[i]) + 1)
      return out.join('')
    }
    out[i] = '0'
  }
  return `1${out.join('')}`
}

/** Round a decimal string to whole rupees, half away from zero ("1234.50" → "1235"). */
export function roundRupees(decimal: string): { negative: boolean; whole: string } {
  const trimmed = decimal.trim()
  const negative = trimmed.startsWith('-')
  const [wholeRaw = '0', frac = ''] = trimmed.replace(/^[-+]/, '').split('.')
  let whole = wholeRaw.replace(/^0+(?=\d)/, '') || '0'
  if ((frac[0] ?? '0') >= '5') whole = incrementDigits(whole)
  return { negative: negative && whole !== '0', whole }
}

/** "142702.04" → "₹1,42,702"; "-22330.28" → "−₹22,330". Whole rupees, for cards and charts. */
export function formatRupees(decimal: string | null | undefined): string {
  if (decimal === null || decimal === undefined || decimal === '') return '—'
  const { negative, whole } = roundRupees(decimal)
  const grouped = groupIndian(whole).slice(0, -3) // drop ".00"
  return `${negative ? MINUS : ''}₹${grouped}`
}

/** "+₹1,000" / "−₹22,330" / "₹0": a change in money. */
export function formatSignedRupees(decimal: string | null | undefined): string {
  if (decimal === null || decimal === undefined || decimal === '') return '—'
  const { negative, whole } = roundRupees(decimal)
  const grouped = groupIndian(whole).slice(0, -3)
  if (whole === '0') return '₹0'
  return `${negative ? MINUS : '+'}₹${grouped}`
}

/** "−93.94" → "₹94 over"; "680.00" → "₹680 left". Never a minus sign. */
export function formatOverLeft(remaining: string): string {
  const { negative, whole } = roundRupees(remaining)
  const amount = `₹${groupIndian(whole).slice(0, -3)}`
  return negative ? `${amount} over` : `${amount} left`
}

function trimOneDecimal(value: number): string {
  const text = (Math.round(value * 10) / 10).toFixed(1)
  return text.endsWith('.0') ? text.slice(0, -2) : text
}

/**
 * Compact axis labels: ₹0, ₹500, ₹50K, ₹1L, ₹1.5L, ₹2Cr. Custom on purpose: Intl's en-IN
 * compact notation prints "T" for thousands. For chart ticks (numbers), not for amounts.
 */
export function formatCompact(value: number): string {
  const sign = value < 0 ? MINUS : ''
  const n = Math.abs(value)
  if (n >= 1e7) return `${sign}₹${trimOneDecimal(n / 1e7)}Cr`
  if (n >= 1e5) return `${sign}₹${trimOneDecimal(n / 1e5)}L`
  if (n >= 1e3) return `${sign}₹${trimOneDecimal(n / 1e3)}K`
  return `${sign}₹${Math.round(n)}`
}

/** 32.7 → "32.7%"; null → "—". */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value < 0 ? MINUS : ''}${Math.abs(value).toFixed(1)}%`
}

/** 4.6 → "+4.6%"; −11.3 → "−11.3%". */
export function formatSignedPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value < 0 ? MINUS : '+'}${Math.abs(value).toFixed(1)}%`
}

/** −10.2 → "−10.2 pts" (percentage points). */
export function formatPts(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value < 0 ? MINUS : '+'}${Math.abs(value).toFixed(1)} pts`
}

function monthParts(month: string): [number, number] {
  const [y, m] = month.split('-').map(Number)
  return [y ?? 0, (m ?? 1) - 1]
}

/** "2026-09" → "September 2026". */
export function formatMonth(month: string): string {
  const [y, m] = monthParts(month)
  return `${MONTHS[m]} ${y}`
}

/** "2026-09" → "Sep". */
export function formatMonthShort(month: string): string {
  return MONTHS[monthParts(month)[1]]!.slice(0, 3)
}

/** "2026-09" → "Sep '26" (chart axes). */
export function formatMonthAxis(month: string): string {
  const [y, m] = monthParts(month)
  return `${MONTHS[m]!.slice(0, 3)} '${String(y).slice(-2)}`
}

/** "2026-09-28" → "28 Sep". */
export function formatDayMonth(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${MONTHS[(m ?? 1) - 1]!.slice(0, 3)}`
}

/** A money string as a number, for chart geometry only (never for sums). */
export function chartNumber(decimal: string): number {
  return Number(decimal)
}
