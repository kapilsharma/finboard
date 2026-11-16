import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// Server mode (ADR-0041), in a real browser: the cookie really is set and sent, and two
// people on one server see only their own data. Run with playwright.server.config.ts.

const PASSWORD = 'e2e long enough passphrase'
const run = Date.now().toString(36) // the database outlives a local rerun; names must not

async function signUp(page: Page, username: string, name: string) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByRole('button', { name: 'Create an account' }).click()
  await page.getByLabel('Username').fill(username)
  await page.getByLabel(/Name shown in the app/).fill(name)
  await page.getByLabel(/^Password/).fill(PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
}

async function signIn(page: Page, username: string, password = PASSWORD) {
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function addAccount(page: Page, name: string) {
  await page.goto('/settings/accounts')
  await page.getByRole('button', { name: 'Add account' }).click()
  const form = page.getByRole('form', { name: 'Save account' })
  await form.getByLabel('Name').fill(name)
  await form.getByRole('button', { name: 'Save account' }).click()
  await expect(page.getByRole('cell', { name, exact: true })).toBeVisible()
}

test('the sign-in page is accessible, in light and dark, and fits a phone', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 800 })
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    expect(results.violations, scheme).toEqual([])
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    )
    expect(overflow, `${scheme}: horizontal scroll at 400 px`).toBe(false)
  }
})

test('sign up, work, sign out, sign in again; a second person sees none of it', async ({
  browser,
}) => {
  const carol = `carol-${run}`
  const dave = `dave-${run}`
  const carolsBrowser = await browser.newContext()
  const page = await carolsBrowser.newPage()

  // Nothing of the app is reachable before signing in.
  await page.goto('/transactions')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Main' })).toHaveCount(0)

  await signUp(page, carol, 'Carol E2E')
  await expect(page.getByText('Carol E2E')).toBeVisible()
  await addAccount(page, 'Carol savings') // a change: needs the session's CSRF token

  // The session cookie can't be read by scripts, and a reload keeps Carol signed in.
  expect(await page.evaluate(() => document.cookie)).not.toContain('finboard_session')
  const cookies = await carolsBrowser.cookies()
  const session = cookies.find((c) => c.name === 'finboard_session')
  expect(session?.httpOnly).toBe(true)
  expect(session?.sameSite).toBe('Strict')
  await page.reload()
  await expect(page.getByRole('cell', { name: 'Carol savings', exact: true })).toBeVisible()

  // Dave, in his own browser, has an empty Finboard.
  const davesBrowser = await browser.newContext()
  const davesPage = await davesBrowser.newPage()
  await signUp(davesPage, dave, 'Dave E2E')
  await davesPage.goto('/settings/accounts')
  await expect(davesPage.getByRole('heading', { name: 'Accounts' })).toBeVisible()
  await expect(davesPage.getByText('Carol savings')).toHaveCount(0)
  await davesBrowser.close()

  // Sign out: back to the sign-in page, and the old pages need a sign-in again.
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.goto('/settings/accounts')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await signIn(page, carol, 'definitely not the password')
  await expect(page.getByRole('alert')).toContainText('Wrong username or password')
  await signIn(page, carol)
  await expect(page.getByRole('cell', { name: 'Carol savings', exact: true })).toBeVisible()
  await carolsBrowser.close()
})
