import type { AccountTotals, Dashboard, IncomeSource } from '../../api/types'
import { LimitBar } from '../../components/LimitBar'
import { chartNumber, formatOverLeft, formatRupees } from '../../lib/format'
import styles from './dashboard.module.css'

export function CategoryLimits({
  data,
  selected,
  onSelect,
}: {
  data: Dashboard
  selected: string | null
  onSelect: (categoryId: string | null) => void
}) {
  const { summary, items } = data.categories
  return (
    <>
      {summary ? (
        <p className={styles.summary}>
          <b>{formatRupees(summary.spent_in_limits)}</b> spent of{' '}
          <b>{formatRupees(summary.limits_total)}</b> in limits,{' '}
          <b className={summary.left.startsWith('-') ? styles.bad : styles.good}>
            {formatOverLeft(summary.left)}
          </b>
          {summary.over_count > 0 && (
            <>
              {' '}
              · <b>{summary.over_count}</b>{' '}
              {summary.over_count === 1 ? 'category over its limit' : 'categories over their limit'}
            </>
          )}
        </p>
      ) : (
        <p className={styles.muted}>No limits set yet.</p>
      )}
      {items.length === 0 && <p className={styles.muted}>Nothing spent in this month.</p>}
      <ul className={styles.bars} aria-label="Categories by share of their limit used">
        {items.map((item) => (
          <li key={item.category.id}>
            <LimitBar
              item={item}
              selected={selected === item.category.id}
              dimmed={selected !== null && selected !== item.category.id}
              onClick={() => onSelect(selected === item.category.id ? null : item.category.id)}
            />
          </li>
        ))}
      </ul>
    </>
  )
}

function SourceBar({ source, top }: { source: IncomeSource; top: number }) {
  const amount = Math.max(0, chartNumber(source.amount))
  const prev = source.prev_amount === null ? null : Math.max(0, chartNumber(source.prev_amount))
  return (
    <li className={styles.sourceRow}>
      <span>{source.category.name}</span>
      <span className={styles.sourceTrack} aria-hidden>
        <span className={styles.sourceBar} style={{ width: `${(amount / top) * 100}%` }} />
        {prev !== null && (
          <span className={styles.sourcePrev} style={{ width: `${(prev / top) * 100}%` }} />
        )}
      </span>
      <span className={styles.num}>
        {formatRupees(source.amount)}
        {source.prev_amount !== null && (
          <span className="visually-hidden">
            , {formatRupees(source.prev_amount)} the month before
          </span>
        )}
      </span>
    </li>
  )
}

export function IncomeBySource({ data }: { data: Dashboard }) {
  const sources = data.income_sources
  if (sources.length === 0) return <p className={styles.muted}>No income in this month.</p>
  const top =
    Math.max(
      ...sources.map((s) =>
        Math.max(chartNumber(s.amount), s.prev_amount === null ? 0 : chartNumber(s.prev_amount)),
      ),
    ) || 1
  return (
    <ul className={styles.bars} aria-label="Income by source">
      {sources.map((s) => (
        <SourceBar key={s.category.id} source={s} top={top} />
      ))}
    </ul>
  )
}

function NetCell({ row }: { row: AccountTotals }) {
  const negative = row.net.startsWith('-')
  return (
    <td className={`${styles.num} ${negative ? styles.bad : styles.good}`}>
      {formatRupees(row.net)}
    </td>
  )
}

export function AccountTable({ data }: { data: Dashboard }) {
  if (data.accounts.length === 0)
    return <p className={styles.muted}>No transactions in this month.</p>
  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col" className={styles.num}>
              Income
            </th>
            <th scope="col" className={styles.num}>
              Spending
            </th>
            <th scope="col" className={styles.num}>
              Invested
            </th>
            <th scope="col" className={styles.num}>
              Net
            </th>
          </tr>
        </thead>
        <tbody>
          {data.accounts.map((row) => (
            <tr key={row.account.id}>
              <th scope="row" className={styles.rowHead}>
                {row.account.name}
              </th>
              <td className={styles.num}>{formatRupees(row.income)}</td>
              <td className={styles.num}>{formatRupees(row.spending)}</td>
              <td className={styles.num}>{formatRupees(row.invested)}</td>
              <NetCell row={row} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
