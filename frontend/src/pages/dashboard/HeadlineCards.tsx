import type { ReactNode } from 'react'
import type { Dashboard } from '../../api/types'
import {
  formatMonthShort,
  formatPct,
  formatPts,
  formatRupees,
  formatSignedPct,
  formatSignedRupees,
} from '../../lib/format'
import { MetricLabel } from './MetricLabel'
import styles from './dashboard.module.css'

/** A change vs the previous month, coloured good/bad *and* said in words (not colour only). */
export function DeltaBadge({
  text,
  value,
  goodWhenUp,
  prevMonth,
}: {
  text: string
  value: number | null
  goodWhenUp: boolean
  prevMonth: string | null
}) {
  if (value === null || !prevMonth) return <span className={styles.note}>No earlier month</span>
  const quality = value === 0 ? null : value > 0 === goodWhenUp ? 'good' : 'bad'
  return (
    <span className={styles.note}>
      <span className={quality ? styles[quality] : undefined}>{text}</span>
      {quality && (
        <span className="visually-hidden"> ({quality === 'good' ? 'better' : 'worse'})</span>
      )}{' '}
      vs {formatMonthShort(prevMonth)}
    </span>
  )
}

function StatCard({
  label,
  metric,
  value,
  children,
}: {
  label: string
  metric: string
  value: string
  children: ReactNode
}) {
  return (
    <section className={styles.stat} aria-label={label}>
      <h2 className={styles.statLabel}>
        <MetricLabel metric={metric}>{label}</MetricLabel>
      </h2>
      <p className={styles.statValue}>{value}</p>
      {children}
    </section>
  )
}

export function HeadlineCards({ data }: { data: Dashboard }) {
  const { headline: h, prev_month: prev } = data
  return (
    <div className={styles.stats}>
      <StatCard label="Income" metric="income" value={formatRupees(h.income.value)}>
        <DeltaBadge
          text={formatSignedPct(h.income.delta_pct)}
          value={h.income.delta_pct}
          goodWhenUp
          prevMonth={prev}
        />
      </StatCard>
      <StatCard label="Spending" metric="spending" value={formatRupees(h.spending.value)}>
        <DeltaBadge
          text={formatSignedPct(h.spending.delta_pct)}
          value={h.spending.delta_pct}
          goodWhenUp={false}
          prevMonth={prev}
        />
      </StatCard>
      <StatCard label="Net saving" metric="net_saving" value={formatRupees(h.net_saving.value)}>
        <DeltaBadge
          text={formatSignedRupees(h.net_saving.delta)}
          value={h.net_saving.delta === null ? null : Number(h.net_saving.delta)}
          goodWhenUp
          prevMonth={prev}
        />
      </StatCard>
      <StatCard label="Savings rate" metric="savings_rate" value={formatPct(h.savings_rate.value)}>
        <DeltaBadge
          text={formatPts(h.savings_rate.delta_pts)}
          value={h.savings_rate.delta_pts}
          goodWhenUp
          prevMonth={prev}
        />
      </StatCard>
      <StatCard label="Invested" metric="invested" value={formatRupees(h.invested.value)}>
        <span className={styles.note}>
          {h.invested.pct_of_net_saving !== null && h.invested.value !== '0.00'
            ? `${formatPct(h.invested.pct_of_net_saving)} of net saving`
            : 'SIPs, mutual funds, deposits'}
        </span>
      </StatCard>
    </div>
  )
}
