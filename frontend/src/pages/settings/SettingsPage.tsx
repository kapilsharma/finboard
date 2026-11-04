import { NavLink, Navigate, useParams } from 'react-router'
import { PageHeader } from '../../components/ui'
import { AccountsTab } from './AccountsTab'
import { CategoriesTab } from './CategoriesTab'
import { ImportHistoryTab } from './ImportHistoryTab'
import { ParsersTab } from './ParsersTab'
import { PreferencesTab } from './PreferencesTab'
import { RulesTab } from './rules/RulesTab'
import { SystemTab } from './SystemTab'
import styles from './settings.module.css'

// Budgets and Data join in later milestones.
const TABS = [
  { id: 'accounts', label: 'Accounts', element: <AccountsTab /> },
  { id: 'categories', label: 'Categories', element: <CategoriesTab /> },
  { id: 'rules', label: 'Rules', element: <RulesTab /> },
  { id: 'parsers', label: 'Parsers', element: <ParsersTab /> },
  { id: 'imports', label: 'Import history', element: <ImportHistoryTab /> },
  { id: 'preferences', label: 'Preferences', element: <PreferencesTab /> },
  { id: 'system', label: 'System', element: <SystemTab /> },
] as const

export function SettingsPage() {
  const { tab } = useParams()
  const current = TABS.find((t) => t.id === tab)
  if (!current) return <Navigate to="/settings/accounts" replace />

  return (
    <>
      <PageHeader title="Settings" />
      <nav aria-label="Settings sections">
        <ul className={styles.tabs}>
          {TABS.map((t) => (
            <li key={t.id}>
              <NavLink
                to={`/settings/${t.id}`}
                className={({ isActive }) => (isActive ? styles.activeTab : undefined)}
              >
                {t.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      {current.element}
    </>
  )
}
