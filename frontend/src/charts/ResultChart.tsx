import { useState } from 'react'
import { max, min } from 'd3-array'
import { scaleBand, scaleLinear } from 'd3-scale'
import { line } from 'd3-shape'
import type { AskChart, AskResult } from '../api/types'
import { chartNumber, formatCompact, formatMonth, formatMonthAxis } from '../lib/format'
import { useElementWidth } from '../lib/useElementWidth'
import { formatCell, type Cell } from './resultFormat'
import styles from './charts.module.css'

const PALETTE = [
  'var(--series-income)',
  'var(--series-spending)',
  'var(--series-net)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
]
const HEIGHT = 240
const ROW = 26

type Kind = AskResult['columns'][number]['kind']

function columnIndex(result: AskResult, name: string | null | undefined): number {
  return result.columns.findIndex((c) => c.name === name)
}

function axisLabel(value: string, kind: Kind): string {
  return kind === 'month' ? formatMonthAxis(value) : value
}

/**
 * An Ask Finboard answer drawn from the server's chart choice (ADR-0012, ADR-0032): bars,
 * grouped bars or lines, or a table. Values come pre-computed; the browser only draws.
 */
export function ResultChart({ result, chart }: { result: AskResult; chart: AskChart | null }) {
  const kind = chart?.kind ?? 'table'
  const xi = columnIndex(result, chart?.x)
  const yi = columnIndex(result, chart?.y)
  if (kind === 'table' || xi < 0 || yi < 0 || result.rows.length === 0)
    return <ResultTable result={result} />
  const si = columnIndex(result, chart?.series)
  if (kind === 'bar' && si < 0 && result.columns[xi]!.kind === 'text')
    return <HorizontalBars result={result} xi={xi} yi={yi} />
  return <ColumnChart result={result} xi={xi} yi={yi} si={si} asLine={kind === 'line'} />
}

export function ResultTable({ result }: { result: AskResult }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.resultTable}>
        <thead>
          <tr>
            {result.columns.map((c) => (
              <th key={c.name} scope="col" className={c.kind === 'text' ? '' : styles.num}>
                {c.name.replaceAll('_', ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, r) => (
            <tr key={r}>
              {row.map((v, i) => {
                const k = result.columns[i]!.kind
                return (
                  <td key={i} className={k === 'text' || k === 'month' ? '' : styles.num}>
                    {formatCell(v, k)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {result.truncated && <p className={styles.tick}>Showing the first 1,000 rows.</p>}
    </div>
  )
}

function valueOf(v: Cell): number {
  return v === null ? 0 : chartNumber(String(v))
}

function HorizontalBars({ result, xi, yi }: { result: AskResult; xi: number; yi: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const W = Math.max(260, width)
  const yKind = result.columns[yi]!.kind
  const rows = result.rows.slice(0, 40)
  const values = rows.map((r) => valueOf(r[yi]!))
  const label = Math.min(160, Math.round(W * 0.38))
  const x = scaleLinear(
    [Math.min(0, min(values) ?? 0), max(values) || 1],
    [label + 8, W - 8],
  ).nice()
  const H = rows.length * ROW + 8
  return (
    <div ref={ref} className={styles.chart}>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Bar chart">
        {rows.map((row, i) => {
          const name = String(row[xi] ?? '—')
          const v = values[i]!
          const y = i * ROW + 4
          return (
            <g key={i}>
              <title>{`${name}: ${formatCell(row[yi]!, yKind)}`}</title>
              <text x={label} y={y + ROW / 2} dy="0.32em" textAnchor="end" className={styles.tick}>
                {name.length > 22 ? `${name.slice(0, 21)}…` : name}
              </text>
              <rect
                x={x(Math.min(0, v))}
                y={y + 3}
                width={Math.abs(x(v) - x(0))}
                height={ROW - 8}
                rx={3}
                fill={PALETTE[0]}
              />
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function ColumnChart({
  result,
  xi,
  yi,
  si,
  asLine,
}: {
  result: AskResult
  xi: number
  yi: number
  si: number
  asLine: boolean
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const W = Math.max(280, width)
  const xKind = result.columns[xi]!.kind
  const yKind = result.columns[yi]!.kind

  const xs: string[] = []
  const series: string[] = []
  const value = new Map<string, Cell>()
  for (const row of result.rows) {
    const xv = String(row[xi] ?? '—')
    const sv = si >= 0 ? String(row[si] ?? '—') : ''
    if (!xs.includes(xv)) xs.push(xv)
    if (!series.includes(sv)) series.push(sv)
    value.set(`${xv}\u0000${sv}`, row[yi] ?? null)
  }
  if (xKind === 'month') xs.sort()
  const at = (xv: string, sv: string) => valueOf(value.get(`${xv}\u0000${sv}`) ?? null)
  const all = xs.flatMap((xv) => series.map((sv) => at(xv, sv)))
  const y = scaleLinear([Math.min(0, min(all) ?? 0), max(all) || 1], [HEIGHT - 26, 14]).nice()
  const ticks = y.ticks(4)
  const left = Math.max(...ticks.map((t) => formatCompact(t).length)) * 7 + 12
  const x = scaleBand(xs, [left, W - 4])
    .paddingInner(0.25)
    .paddingOuter(0.1)
  const sub = scaleBand(series, [0, x.bandwidth()]).padding(0.08)
  const centre = (xv: string) => (x(xv) ?? 0) + x.bandwidth() / 2
  const step = Math.ceil(xs.length / Math.max(1, Math.floor((W - left) / 60)))
  const colour = (i: number) => PALETTE[i % PALETTE.length]!
  const describe = (xv: string) =>
    `${xKind === 'month' ? formatMonth(xv) : xv}: ` +
    series
      .map(
        (sv) => `${sv ? `${sv} ` : ''}${formatCell(value.get(`${xv}\u0000${sv}`) ?? null, yKind)}`,
      )
      .join(', ')

  return (
    <div ref={ref} className={styles.chart}>
      {series.length > 1 && (
        <ul className={styles.legend} aria-hidden>
          {series.map((sv, i) => (
            <li key={sv}>
              <span className={styles.swatch} style={{ background: colour(i) }} />
              {sv}
            </li>
          ))}
        </ul>
      )}
      <svg
        width="100%"
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={asLine ? 'Line chart' : 'Bar chart'}
      >
        {ticks.map((t) => (
          <g key={t} aria-hidden>
            <line
              x1={left}
              x2={W - 4}
              y1={y(t)}
              y2={y(t)}
              className={t === 0 ? styles.axis : styles.grid}
            />
            <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className={styles.tick}>
              {formatCompact(t)}
            </text>
          </g>
        ))}
        {xs.map((xv, i) => (
          <g
            key={xv}
            onMouseEnter={() => setHover(xv)}
            onMouseLeave={() => setHover(null)}
            style={{ opacity: hover === null || hover === xv ? 1 : 0.55 }}
          >
            <title>{describe(xv)}</title>
            <rect x={x(xv)} width={x.bandwidth()} y={0} height={HEIGHT} fill="transparent" />
            {!asLine &&
              series.map((sv, s) => {
                const v = at(xv, sv)
                const bw = Math.min(36, sub.bandwidth())
                return (
                  <rect
                    key={sv}
                    x={(x(xv) ?? 0) + (sub(sv) ?? 0) + (sub.bandwidth() - bw) / 2}
                    width={bw}
                    y={y(Math.max(0, v))}
                    height={Math.abs(y(v) - y(0))}
                    rx={3}
                    fill={colour(s)}
                  />
                )
              })}
            {i % step === 0 && (
              <text x={centre(xv)} y={HEIGHT - 8} textAnchor="middle" className={styles.tick}>
                {axisLabel(xv.length > 12 ? `${xv.slice(0, 11)}…` : xv, xKind)}
              </text>
            )}
          </g>
        ))}
        {asLine &&
          series.map((sv, s) => (
            <path
              key={sv}
              d={
                line<string>()
                  .x((xv) => centre(xv))
                  .y((xv) => y(at(xv, sv)))(xs) ?? undefined
              }
              fill="none"
              stroke={colour(s)}
              strokeWidth={2}
              strokeLinejoin="round"
              pointerEvents="none"
            />
          ))}
      </svg>
    </div>
  )
}
