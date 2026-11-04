import { useEffect, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { TxnListItem } from '../../api/types'
import { CATEGORY_TYPE_LABELS } from '../../api/types'
import { formatDayMonth, formatMoney } from '../../lib/format'
import { RecategoriseDialog } from './RecategoriseDialog'
import styles from './transactions.module.css'

export type SortKey = 'date' | 'description' | 'account' | 'category' | 'type' | 'amount'

const COLUMNS: { key: SortKey; label: string; className?: string }[] = [
  { key: 'date', label: 'Date' },
  { key: 'description', label: 'Description' },
  { key: 'account', label: 'Account', className: styles.hideNarrow },
  { key: 'category', label: 'Category' },
  { key: 'type', label: 'Type', className: styles.hideNarrow },
  { key: 'amount', label: 'Amount', className: styles.num },
]

const ROW_HEIGHT = 37

function Row({ txn, onCategorise }: { txn: TxnListItem; onCategorise: (t: TxnListItem) => void }) {
  const classes = [txn.needs_review && styles.review, txn.type === 'transfer' && styles.transfer]
  return (
    <tr className={classes.filter(Boolean).join(' ')}>
      <td className={styles.date}>
        {formatDayMonth(txn.date)}
        {txn.needs_review && <span className="visually-hidden"> (needs a category)</span>}
      </td>
      <td className={styles.description}>{txn.description}</td>
      <td className={styles.hideNarrow}>{txn.account_name}</td>
      <td>
        <button
          type="button"
          className={`link ${styles.categoryButton}`}
          onClick={() => onCategorise(txn)}
          aria-label={`${txn.category_name}: change the category of ${txn.description}`}
        >
          {txn.category_name}
        </button>
      </td>
      <td className={styles.hideNarrow}>{CATEGORY_TYPE_LABELS[txn.type]}</td>
      <td className={`${styles.num} ${txn.type === 'income' ? styles.income : ''}`}>
        {txn.direction === 'credit' && txn.type !== 'income' && (
          <span className="visually-hidden">In: </span>
        )}
        {formatMoney(txn.amount)}
      </td>
    </tr>
  )
}

/**
 * Transactions with sortable headers (`aria-sort`), a yellow edge on rows that need a category,
 * muted transfers and green income. Clicking a category opens the categorise dialog. With
 * `virtual`, only the visible rows are rendered (the Transactions page).
 */
export function TransactionsTable({
  items,
  sort,
  order,
  onSort,
  virtual = false,
  onEndReached,
}: {
  items: TxnListItem[]
  sort: SortKey
  order: 'asc' | 'desc'
  onSort: (key: SortKey, order: 'asc' | 'desc') => void
  virtual?: boolean
  onEndReached?: () => void
}) {
  const [editing, setEditing] = useState<TxnListItem | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  // oxlint-disable-next-line react/incompatible-library -- this project doesn't use React Compiler
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    enabled: virtual,
    initialRect: { width: 1000, height: 600 }, // first paint before layout (and in tests)
  })
  const virtualRows = virtual ? virtualizer.getVirtualItems() : []
  const last = virtualRows[virtualRows.length - 1]
  const nearEnd = virtual && last !== undefined && last.index >= items.length - 20
  useEffect(() => {
    if (nearEnd) onEndReached?.()
  }, [nearEnd, items.length, onEndReached])

  const visible = virtual ? virtualRows.map((v) => items[v.index]!) : items
  const padTop = virtual && virtualRows[0] ? virtualRows[0].start : 0
  const padBottom = virtual && last ? virtualizer.getTotalSize() - last.end : 0

  return (
    <>
      <div ref={scroller} className={virtual ? styles.scroller : styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              {COLUMNS.map((c) => {
                const active = sort === c.key
                const next =
                  active && order === 'desc'
                    ? 'asc'
                    : active
                      ? 'desc'
                      : c.key === 'date' || c.key === 'amount'
                        ? 'desc'
                        : 'asc'
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className={c.className}
                    aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
                  >
                    <button
                      type="button"
                      className={styles.sortButton}
                      onClick={() => onSort(c.key, next)}
                    >
                      {c.label}
                      <span aria-hidden className={styles.sortMark}>
                        {active ? (order === 'asc' ? '▲' : '▼') : ''}
                      </span>
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {padTop > 0 && (
              <tr aria-hidden>
                <td colSpan={COLUMNS.length} style={{ height: padTop, padding: 0, border: 0 }} />
              </tr>
            )}
            {visible.map((txn) => (
              <Row key={txn.id} txn={txn} onCategorise={setEditing} />
            ))}
            {padBottom > 0 && (
              <tr aria-hidden>
                <td colSpan={COLUMNS.length} style={{ height: padBottom, padding: 0, border: 0 }} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {editing && <RecategoriseDialog txn={editing} onClose={() => setEditing(null)} />}
    </>
  )
}
