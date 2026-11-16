import { NavLink, Outlet } from 'react-router'
import { useLogout, useMe } from '../api/hooks'
import { AuthGate } from './AuthGate'
import { ThemeSync } from '../theme/ThemeSync'
import styles from './AppLayout.module.css'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/transactions', label: 'Transactions' },
  { to: '/review', label: 'Review' },
  { to: '/import', label: 'Import' },
  { to: '/settings', label: 'Settings' },
]

/** Server mode only: who is signed in, and the way out. Local mode has no sign-in. */
function SignedInAs() {
  const me = useMe()
  const logout = useLogout()
  if (me.data?.mode !== 'server') return null
  return (
    <div className={styles.account}>
      <span title={`Signed in as ${me.data.username}`}>{me.data.display_name}</span>
      <button className="link" disabled={logout.isPending} onClick={() => logout.mutate()}>
        Sign out
      </button>
    </div>
  )
}

export function AppLayout() {
  return (
    <AuthGate>
      <ThemeSync />
      <header className={styles.header}>
        <span className={styles.brand}>Finboard</span>
        <nav aria-label="Main">
          <ul className={styles.nav}>
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? styles.active : undefined)}
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <SignedInAs />
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </AuthGate>
  )
}
