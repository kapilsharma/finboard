import { usePreferences, useUpdatePreferences } from '../../api/hooks'
import { errorMessage } from '../../api/client'
import type { Theme } from '../../api/types'
import { Card, ErrorText } from '../../components/ui'
import { applyTheme } from '../../theme/theme'
import styles from './settings.module.css'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'system', label: 'Match my system' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

export function PreferencesTab() {
  const prefs = usePreferences()
  const update = useUpdatePreferences()

  return (
    <Card title="Preferences">
      <fieldset className={styles.radioGroup}>
        <legend className={styles.muted}>Theme</legend>
        {THEMES.map((t) => (
          <label key={t.value}>
            <input
              type="radio"
              name="theme"
              value={t.value}
              checked={prefs.data?.theme === t.value}
              disabled={!prefs.data || update.isPending}
              onChange={() => {
                applyTheme(t.value) // instant feedback; saved below
                update.mutate({ theme: t.value })
              }}
            />
            {t.label}
          </label>
        ))}
      </fieldset>
      <p className={styles.muted} style={{ marginTop: 16 }}>
        Currency: Indian rupee (₹), Indian number grouping (₹1,42,000).
      </p>
      <ErrorText>{update.isError ? errorMessage(update.error) : null}</ErrorText>
    </Card>
  )
}
