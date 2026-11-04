import { useEffect, useState } from 'react'
import { useAccounts } from '../../api/hooks'
import { useDebounced } from '../../lib/useDebounced'
import type { UrlState } from '../../lib/useUrlState'
import { CategoryPicker } from '../CategoryPicker'
import styles from './transactions.module.css'

type Update = (changes: Partial<Record<keyof UrlState, string | boolean | null>>) => void

/** Search, account, category and "needs review" filters, kept in the URL so they persist
 *  across month changes and reloads (HANDOVER §4.7). */
export function TransactionFilters({ state, update }: { state: UrlState; update: Update }) {
  const accounts = useAccounts()
  const [q, setQ] = useState(state.q)
  const debounced = useDebounced(q, 250)
  const urlQ = state.q
  useEffect(() => {
    if (debounced !== urlQ) update({ q: debounced }) // push typed text to the URL, debounced
  }, [debounced, urlQ, update])
  const active = Boolean(q || state.q || state.account || state.category || state.review)

  return (
    <div className={styles.filters} role="search" aria-label="Filter transactions">
      <label className={styles.search}>
        <span className="visually-hidden">Search description, category, account</span>
        <input
          type="search"
          placeholder="Search description, category, account"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
      <label>
        <span className="visually-hidden">Account</span>
        <select
          value={state.account ?? ''}
          onChange={(e) => update({ account: e.target.value || null })}
        >
          <option value="">All accounts</option>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="visually-hidden">Category</span>
        <CategoryPicker
          value={state.category ?? ''}
          onChange={(id) => update({ category: id || null })}
          placeholder="All categories"
        />
      </label>
      <button
        type="button"
        aria-pressed={state.review}
        onClick={() => update({ review: !state.review })}
      >
        Needs review only
      </button>
      {active && (
        <button
          type="button"
          className="link"
          onClick={() => {
            setQ('') // the debounced effect clears q in the URL
            update({ account: null, category: null, review: null })
          }}
        >
          Clear filters
        </button>
      )}
    </div>
  )
}
