import { afterEach, describe, expect, it } from 'vitest'
import { THEME_STORAGE_KEY, applyTheme } from './theme'

describe('applyTheme', () => {
  afterEach(() => {
    delete document.documentElement.dataset.theme
    localStorage.clear()
  })

  it('sets an explicit theme on <html> and remembers it for the next first paint', () => {
    applyTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('removes the override for "system" so CSS follows the OS', () => {
    applyTheme('light')
    applyTheme('system')
    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('system')
  })
})
