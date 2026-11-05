import type { AskResult } from '../api/types'
import { formatMoney, formatMonth } from '../lib/format'

export type Cell = string | number | null
type Kind = AskResult['columns'][number]['kind']

/** One cell as text: money in ₹ with lakh grouping, months as "September 2026". */
export function formatCell(value: Cell, kind: Kind): string {
  if (value === null) return '—'
  if (kind === 'money') return formatMoney(String(value))
  if (kind === 'month' && typeof value === 'string') return formatMonth(value)
  if (kind === 'count' || kind === 'number') return Number(value).toLocaleString('en-IN')
  return String(value)
}
