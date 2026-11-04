import type { Dashboard } from '../../api/types'
import { formatMonth, formatMonthShort, formatPct, formatRupees } from '../../lib/format'
import styles from './dashboard.module.css'

/** "In September 2026 you saved ₹46,662, 32.7% of your income. Spending was 4.6% higher than
 *  Aug. Biggest spend: Rent at ₹32,000." */
export function Takeaway({ data }: { data: Dashboard }) {
  const { headline: h } = data
  const saved = !h.net_saving.value.startsWith('-')
  const change = h.spending.delta_pct
  return (
    <p className={styles.takeaway}>
      In {formatMonth(data.month)} you {saved ? 'saved' : 'overspent by'}{' '}
      <b>{formatRupees(h.net_saving.value.replace(/^-/, ''))}</b>
      {h.savings_rate.value !== null && (
        <>
          , <b>{formatPct(h.savings_rate.value)}</b> of your income
        </>
      )}
      .
      {change !== null && data.prev_month && (
        <>
          {' '}
          Spending was <b>{formatPct(Math.abs(change))}</b> {change >= 0 ? 'higher' : 'lower'} than{' '}
          {formatMonthShort(data.prev_month)}.
        </>
      )}
      {data.biggest_spend && (
        <>
          {' '}
          Biggest spend: <b>{data.biggest_spend.category.name}</b> at{' '}
          <b>{formatRupees(data.biggest_spend.amount)}</b>.
        </>
      )}
    </p>
  )
}

export function MonthSelect({
  months,
  value,
  onChange,
}: {
  months: string[]
  value: string
  onChange: (month: string) => void
}) {
  const options = months.includes(value) ? months : [value, ...months]
  return (
    <label className={styles.monthSelect}>
      <span className="visually-hidden">Month</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((m) => (
          <option key={m} value={m}>
            {formatMonth(m)}
          </option>
        ))}
      </select>
    </label>
  )
}

export function ReviewBanner({
  count,
  month,
  onShow,
}: {
  count: number
  month: string
  onShow: () => void
}) {
  if (count === 0) return null
  return (
    <button type="button" className={styles.banner} onClick={onShow}>
      <b>{count}</b> {count === 1 ? 'transaction' : 'transactions'} in {formatMonth(month)} still
      need{count === 1 ? 's' : ''} a category. Show {count === 1 ? 'it' : 'them'} →
    </button>
  )
}
