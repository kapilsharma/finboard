import type { CategoryLimit } from '../api/types'
import { chartNumber, formatOverLeft, formatRupees } from '../lib/format'
import styles from './LimitBar.module.css'

/**
 * One category against its monthly limit (HANDOVER §4.7): grey track = the limit, fill = spent;
 * green with "₹X left" while under, red with "₹X over" and a tick at the limit once over;
 * a muted bar and "No limit set" without a limit. Plain HTML/CSS (ADR-0012).
 */
export function LimitBar({
  item,
  selected = false,
  dimmed = false,
  onClick,
}: {
  item: CategoryLimit
  selected?: boolean
  dimmed?: boolean
  onClick?: () => void
}) {
  const spent = Math.max(0, chartNumber(item.spent))
  const limit = item.limit === null ? null : chartNumber(item.limit)
  const top = Math.max(spent, limit ?? 0) || 1
  const over = item.status === 'over'
  const name = item.category.name

  const value =
    item.limit === null ? (
      <>
        <span>{formatRupees(item.spent)}</span>
        <span className={styles.sub}>No limit set</span>
      </>
    ) : (
      <>
        <span className={over ? styles.over : styles.ok}>
          {formatOverLeft(item.remaining ?? '0')}
        </span>
        <span className={styles.sub}>
          {formatRupees(item.spent)} of {formatRupees(item.limit)}
        </span>
      </>
    )

  return (
    <button
      type="button"
      className={`${styles.row} ${selected ? styles.selected : ''}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      <span className={styles.label}>{name}</span>
      <span className={styles.track} aria-hidden>
        {limit === null ? (
          <span className={styles.noLimit} style={{ width: '100%' }} />
        ) : (
          <>
            <span className={styles.limit} style={{ width: `${(limit / top) * 100}%` }} />
            <span
              className={`${styles.fill} ${over ? styles.fillOver : styles.fillOk}`}
              style={{ width: `${(spent / top) * 100}%`, opacity: dimmed ? 0.4 : 1 }}
              data-testid="limit-fill"
            />
            {over && (
              <span
                className={styles.tick}
                style={{ left: `${(limit / top) * 100}%` }}
                data-testid="limit-tick"
              />
            )}
          </>
        )}
      </span>
      <span className={styles.value}>{value}</span>
    </button>
  )
}
