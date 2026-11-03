import type { ReactNode } from 'react'
import { useMe } from '../api/hooks'
import { errorMessage } from '../api/client'
import styles from './AuthGate.module.css'

/** Renders the app only once we know who the user is. In local mode this always succeeds;
 *  a future login screen (server mode, M8) slots in here without touching the pages. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe()

  if (me.isPending) {
    return (
      <p className={styles.state} role="status">
        Loading…
      </p>
    )
  }
  if (me.isError) {
    return (
      <div className={styles.state} role="alert">
        <h1>Can't reach Finboard</h1>
        <p>
          The Finboard server isn't responding ({errorMessage(me.error)}). Check that it is running,
          then try again.
        </p>
        <button className="primary" onClick={() => void me.refetch()}>
          Try again
        </button>
      </div>
    )
  }
  return <>{children}</>
}
