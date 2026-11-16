import { useState, type FormEvent } from 'react'
import { useChangePassword, useMe, usePreferences, useUpdatePreferences } from '../../api/hooks'
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

/** Server mode only: change the password you sign in with. */
function PasswordCard() {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again !== '' && next !== again

  function submit(event: FormEvent) {
    event.preventDefault()
    if (next !== again) return
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent('')
          setNext('')
          setAgain('')
        },
      },
    )
  }

  return (
    <Card title="Password">
      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          Current password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          New password
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            maxLength={128}
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          New password again
          <input
            type="password"
            autoComplete="new-password"
            required
            value={again}
            onChange={(e) => setAgain(e.target.value)}
          />
        </label>
        <div className={styles.formActions}>
          <button className="primary" type="submit" disabled={change.isPending || mismatch}>
            Change password
          </button>
        </div>
      </form>
      <p className={styles.muted} style={{ marginTop: 12 }}>
        At least 10 characters. Changing it signs you out everywhere else.
      </p>
      {change.isSuccess && <p role="status">Password changed.</p>}
      <ErrorText>
        {mismatch
          ? 'The two new passwords differ.'
          : change.isError
            ? errorMessage(change.error)
            : null}
      </ErrorText>
    </Card>
  )
}

export function PreferencesTab() {
  const prefs = usePreferences()
  const update = useUpdatePreferences()
  const me = useMe()

  return (
    <>
      <PreferencesCard prefs={prefs} update={update} />
      {me.data?.mode === 'server' && <PasswordCard />}
    </>
  )
}

function PreferencesCard({
  prefs,
  update,
}: {
  prefs: ReturnType<typeof usePreferences>
  update: ReturnType<typeof useUpdatePreferences>
}) {
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
