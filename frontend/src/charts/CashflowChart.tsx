import { useState } from 'react'
import { max, min } from 'd3-array'
import { scaleBand, scaleLinear } from 'd3-scale'
import { line } from 'd3-shape'
import type { CashflowMonth } from '../api/types'
import {
  chartNumber,
  formatCompact,
  formatMonth,
  formatMonthAxis,
  formatRupees,
} from '../lib/format'
import { useElementWidth } from '../lib/useElementWidth'
import styles from './charts.module.css'

const HEIGHT = 240
const MARGIN = { top: 14, bottom: 26, right: 4 }
const SERIES = [
  { key: 'income', label: 'Income', colour: 'var(--series-income)' },
  { key: 'spending', label: 'Spending', colour: 'var(--series-spending)' },
] as const

/**
 * Cash flow by month (ADR-0012): grouped income/spending bars and a net-saving line. The
 * selected month is highlighted; click or press Enter on a month to select it.
 */
export function CashflowChart({
  months,
  selected,
  onSelect,
}: {
  months: CashflowMonth[]
  selected: string
  onSelect: (month: string) => void
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const W = Math.max(280, width)
  const rows = months.map((m) => ({
    month: m.month,
    income: chartNumber(m.income),
    spending: chartNumber(m.spending),
    net: chartNumber(m.net_saving),
    source: m,
  }))

  const hi = max(rows, (r) => Math.max(r.income, r.spending)) || 1
  const lo = Math.min(0, min(rows, (r) => Math.min(r.net, r.spending, r.income)) ?? 0)
  const y = scaleLinear([lo, hi], [HEIGHT - MARGIN.bottom, MARGIN.top]).nice()
  const ticks = y.ticks(4)
  const left = Math.max(...ticks.map((t) => formatCompact(t).length)) * 7 + 12
  const x = scaleBand(
    rows.map((r) => r.month),
    [left, W - MARGIN.right],
  )
    .paddingInner(0.3)
    .paddingOuter(0.15)
  const sub = scaleBand(['income', 'spending'], [0, x.bandwidth()]).padding(0.1)
  const barWidth = Math.min(32, sub.bandwidth())
  const centre = (month: string) => (x(month) ?? 0) + x.bandwidth() / 2
  const labelStep = Math.ceil(rows.length / Math.max(1, Math.floor((W - left) / 56)))
  const path = line<(typeof rows)[number]>()
    .x((r) => centre(r.month))
    .y((r) => y(r.net))(rows)
  const tip = rows.find((r) => r.month === hover)

  return (
    <div ref={ref} className={styles.chart}>
      <ul className={styles.legend} aria-hidden>
        {[...SERIES, { key: 'net', label: 'Net saving', colour: 'var(--series-net)' }].map((s) => (
          <li key={s.key}>
            <span className={styles.swatch} style={{ background: s.colour }} />
            {s.label}
          </li>
        ))}
      </ul>
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="group"
        aria-label="Cash flow by month. Choose a month to look at it."
      >
        {ticks.map((t) => (
          <g key={t} aria-hidden>
            <line
              x1={left}
              x2={W - MARGIN.right}
              y1={y(t)}
              y2={y(t)}
              className={t === 0 ? styles.axis : styles.grid}
            />
            <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className={styles.tick}>
              {formatCompact(t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const isSelected = r.month === selected
          const name = `${formatMonth(r.month)}: income ${formatRupees(r.source.income)}, spending ${formatRupees(r.source.spending)}, net saving ${formatRupees(r.source.net_saving)}`
          return (
            <g
              key={r.month}
              role="button"
              tabIndex={0}
              aria-label={name}
              aria-pressed={isSelected}
              className={styles.month}
              style={{ opacity: isSelected || hover === r.month ? 1 : 0.45 }}
              onClick={() => onSelect(r.month)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onSelect(r.month)
                }
              }}
              onMouseEnter={() => setHover(r.month)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(r.month)}
              onBlur={() => setHover(null)}
            >
              <title>{name}</title>
              <rect
                x={(x(r.month) ?? 0) - (x.step() * x.paddingInner()) / 2}
                width={x.step()}
                y={0}
                height={HEIGHT}
                fill="transparent"
              />
              {SERIES.map((s) => {
                const value = r[s.key]
                return (
                  <rect
                    key={s.key}
                    x={(x(r.month) ?? 0) + (sub(s.key) ?? 0) + (sub.bandwidth() - barWidth) / 2}
                    width={barWidth}
                    y={y(Math.max(0, value))}
                    height={Math.abs(y(value) - y(0))}
                    rx={4}
                    fill={s.colour}
                  />
                )
              })}
              <text
                x={centre(r.month)}
                y={HEIGHT - 6}
                textAnchor="middle"
                className={`${styles.tick} ${isSelected ? styles.selectedTick : ''}`}
              >
                {i % labelStep === 0 || isSelected ? formatMonthAxis(r.month) : ''}
              </text>
            </g>
          )
        })}
        {path && <path d={path} className={styles.netLine} aria-hidden />}
        {rows.map((r) => (
          <circle
            key={r.month}
            cx={centre(r.month)}
            cy={y(r.net)}
            r={4}
            className={styles.netDot}
            aria-hidden
          />
        ))}
      </svg>
      {tip && (
        <div
          className={styles.tooltip}
          style={{ left: Math.min(centre(tip.month) + 12, W - 180) }}
          aria-hidden
        >
          <strong>{formatMonth(tip.month)}</strong>
          <span>Income {formatRupees(tip.source.income)}</span>
          <span>Spending {formatRupees(tip.source.spending)}</span>
          <span>Net saving {formatRupees(tip.source.net_saving)}</span>
        </div>
      )}
      <div className="visually-hidden">
        <table>
          <caption>Cash flow by month</caption>
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col">Income</th>
              <th scope="col">Spending</th>
              <th scope="col">Net saving</th>
            </tr>
          </thead>
          <tbody>
            {months.map((m) => (
              <tr key={m.month}>
                <th scope="row">{formatMonth(m.month)}</th>
                <td>{formatRupees(m.income)}</td>
                <td>{formatRupees(m.spending)}</td>
                <td>{formatRupees(m.net_saving)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
