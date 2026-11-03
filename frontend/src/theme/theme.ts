import type { Theme } from '../api/types'

export const THEME_STORAGE_KEY = 'finboard.theme'

/** Apply a theme to <html>. `system` removes the override so CSS follows the OS. */
export function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'system') delete root.dataset.theme
  else root.dataset.theme = theme
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme) // read by index.html before first paint
  } catch {
    // storage unavailable (private mode): the theme still applies for this page view
  }
}
