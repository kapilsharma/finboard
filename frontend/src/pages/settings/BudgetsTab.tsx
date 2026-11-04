import { useState, type FormEvent } from 'react'
import { errorMessage } from '../../api/client'
import {
  useBudgetHistory,
  useCategories,
  useDeleteBudgetChange,
  usePutBudget,
} from '../../api/hooks'
import type { Budget, Category } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { formatMonth, formatRupees } from '../../lib/format'
import styles from './settings.module.css'

const AMOUNT = /^\d{1,12}(\.\d{1,2})?$/

function thisMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/** The change in force for `month` (the latest one starting on or before it). */
function inForce(history: Budget[], month: string): Budget | undefined {
  return history.filter((b) => b.effective_from.slice(0, 7) <= month).at(-1)
}

function ChangeForm({ category, onDone }: { category: Category; onDone: () => void }) {
  const put = usePutBudget()
  const [month, setMonth] = useState(thisMonth())
  const [limit, setLimit] = useState('')
  const [noLimit, setNoLimit] = useState(false)
  const valid = noLimit || AMOUNT.test(limit)

  function submit(event: FormEvent) {
    event.preventDefault()
    put.mutate(
      { categoryId: category.id, month, limit: noLimit ? null : limit },
      { onSuccess: onDone },
    )
  }

  return (
    <form
      onSubmit={submit}
      aria-label={`Change the limit for ${category.name}`}
      className={styles.inlineForm}
    >
      <label className={styles.field}>
        From
        <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} required />
      </label>
      <label className={styles.field}>
        Monthly limit (₹)
        <input
          inputMode="decimal"
          value={limit}
          onChange={(e) => setLimit(e.target.value.trim())}
          disabled={noLimit}
          aria-invalid={!noLimit && limit !== '' && !AMOUNT.test(limit)}
          required={!noLimit}
        />
      </label>
      <label className={styles.checkboxField}>
        <input type="checkbox" checked={noLimit} onChange={(e) => setNoLimit(e.target.checked)} />
        No limit
      </label>
      <div className={styles.formActions}>
        <button type="submit" className="primary" disabled={!valid || !month || put.isPending}>
          Save
        </button>
        <button type="button" onClick={onDone}>
          Cancel
        </button>
      </div>
      <ErrorText>{put.isError ? errorMessage(put.error) : null}</ErrorText>
      <p className={styles.muted}>
        Months before {month ? formatMonth(month) : 'it'} keep their limit.
      </p>
    </form>
  )
}

function BudgetRow({ category, history }: { category: Category; history: Budget[] }) {
  const [editing, setEditing] = useState(false)
  const undo = useDeleteBudgetChange()
  const current = inForce(history, thisMonth())
  const limitText = (b: Budget | undefined) =>
    b === undefined
      ? 'No limit set'
      : b.monthly_limit === null
        ? 'No limit'
        : formatRupees(b.monthly_limit)

  return (
    <tr>
      <th scope="row" className={styles.rowHead}>
        {category.name}
      </th>
      <td className={styles.num}>{limitText(current)}</td>
      <td>
        {history.length === 0 ? (
          <span className={styles.muted}>—</span>
        ) : (
          <ul className={styles.history} aria-label={`Limit changes for ${category.name}`}>
            {history.map((b) => {
              const month = b.effective_from.slice(0, 7)
              return (
                <li key={b.effective_from}>
                  {limitText(b)} from {formatMonth(month)}
                  <button
                    type="button"
                    className="link danger"
                    disabled={undo.isPending}
                    onClick={() => undo.mutate({ categoryId: category.id, month })}
                    aria-label={`Undo the ${category.name} change from ${formatMonth(month)}`}
                  >
                    Undo
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        {editing && <ChangeForm category={category} onDone={() => setEditing(false)} />}
        <ErrorText>{undo.isError ? errorMessage(undo.error) : null}</ErrorText>
      </td>
      <td className={styles.actions}>
        {!editing && (
          <button
            className="link"
            onClick={() => setEditing(true)}
            aria-label={`Change the limit for ${category.name}`}
          >
            Change
          </button>
        )}
      </td>
    </tr>
  )
}

/** Monthly limits per expense category, with their history (ARCHITECTURE §5). */
export function BudgetsTab() {
  const categories = useCategories()
  const history = useBudgetHistory()
  const expense = (categories.data ?? []).filter((c) => c.type === 'expense' && !c.archived)
  const byCategory = new Map<string, Budget[]>()
  for (const b of history.data ?? [])
    byCategory.set(b.category_id, [...(byCategory.get(b.category_id) ?? []), b])

  return (
    <Card title="Monthly limits">
      <p className={styles.muted}>
        A limit applies from the month you choose until you change it again. Earlier months keep the
        limit they had, so past months on the dashboard don&apos;t change.
      </p>
      {(categories.isPending || history.isPending) && <p className={styles.muted}>Loading…</p>}
      <ErrorText>
        {categories.isError
          ? errorMessage(categories.error)
          : history.isError
            ? errorMessage(history.error)
            : null}
      </ErrorText>
      {expense.length > 0 && (
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th scope="col">Category</th>
                <th scope="col" className={styles.num}>
                  This month
                </th>
                <th scope="col">Changes</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {expense.map((c) => (
                <BudgetRow key={c.id} category={c} history={byCategory.get(c.id) ?? []} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
