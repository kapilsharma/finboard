import type { UseQueryResult } from '@tanstack/react-query'
import { errorMessage } from '../../api/client'
import type { RuleTest } from '../../api/types'
import styles from './categorise.module.css'

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

/** "Would match 12 transactions (8 currently different) · 2 taken by earlier rules". */
export function RuleTestSummary({ test }: { test: UseQueryResult<RuleTest> }) {
  if (test.fetchStatus === 'idle' && test.isPending) return null
  if (test.isError)
    return (
      <p className={styles.testError} role="status">
        {errorMessage(test.error)}
      </p>
    )
  if (!test.data)
    return (
      <p className={styles.test} role="status">
        Counting matches…
      </p>
    )
  const { match_count, would_change, shadowed, shadowed_by } = test.data
  return (
    <p className={styles.test} role="status" aria-live="polite">
      Would match {plural(match_count, 'transaction')} ({would_change} currently different)
      {shadowed > 0 && (
        <>
          {' · '}
          <span className={styles.warnText}>
            {shadowed} taken by earlier rules ({shadowed_by.map((s) => s.pattern).join(', ')})
          </span>
        </>
      )}
    </p>
  )
}
