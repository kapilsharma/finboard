import type { ReactNode } from 'react'
import { useMe } from '../api/hooks'
import { ApiError, errorMessage } from '../api/client'
import { SignInPage } from './SignInPage'
import styles from './AuthGate.module.css'

/** Renders the app only once we know who the user is. In local mode that always succeeds.
 *  In server mode a 401 from /me means nobody is signed in, and the sign-in page shows
 *  instead (ADR-0041). */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe()

  if (me.isPending) {
    return (
      <p className={styles.state} role="status">
        Loading…
      </p>
    )
  }
  if (me.error instanceof ApiError && me.error.status === 401) {
    return <SignInPage onSignedIn={() => void me.refetch()} />
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
