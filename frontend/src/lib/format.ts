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
