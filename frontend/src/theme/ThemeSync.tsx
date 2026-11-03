import { useEffect } from 'react'
import { usePreferences } from '../api/hooks'
import { applyTheme } from './theme'

/** Keeps <html data-theme> in sync with the user's saved preference. */
export function ThemeSync() {
  const { data } = usePreferences()
  useEffect(() => {
    if (data) applyTheme(data.theme)
  }, [data])
  return null
}
