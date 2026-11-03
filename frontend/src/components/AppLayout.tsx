import { NavLink, Outlet } from 'react-router'
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
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </AuthGate>
  )
}
