import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

// The stack loads the handover's synthetic demo data (stack.py), so September 2026 shows the
// approved mockup's figures (docs/handover/design/dashboard-mockup.png).

async function openSeptember(page: Page) {
  await page.goto('/?month=2026-09')
  await expect(page.getByText(/In September 2026 you saved/)).toBeVisible()
}

function transactionRows(page: Page) {
  return page.locator('#transactions tbody tr')
}

test('the headline matches the approved mockup', async ({ page }) => {
  await openSeptember(page)
  await expect(page.getByText(/In September 2026 you saved/)).toHaveText(
    'In September 2026 you saved ₹46,662, 32.7% of your income. Spending was 4.6% higher than Aug. Biggest spend: Rent at ₹32,000.',
  )
  await expect(page.getByRole('region', { name: 'Income', exact: true })).toContainText('₹1,42,702')
  await expect(page.getByRole('region', { name: 'Spending', exact: true })).toContainText('₹96,040')
  await expect(page.getByRole('region', { name: 'Net saving', exact: true })).toContainText(
    '−₹22,330',
  )
  await expect(page.getByRole('region', { name: 'Savings rate', exact: true })).toContainText(
    '−10.2 pts',
  )
  await expect(page.getByText('₹94 over')).toBeVisible()
  await expect(page.getByText(/2 categories over their limit/)).toBeVisible()
  await expect(transactionRows(page)).toHaveCount(29)
})

test('the review banner shows the transactions that need a category', async ({ page }) => {
  await openSeptember(page)
  await page
    .getByRole('button', { name: /2 transactions in September 2026 still need a category/ })
    .click()
  await expect(page).toHaveURL(/review=1/)
  await expect(transactionRows(page)).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Needs review only' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('a category filters the list, and filters survive month changes and reloads', async ({
  page,
}) => {
  await openSeptember(page)
  await page
    .getByRole('list', { name: 'Categories by share of their limit used' })
    .getByRole('button', { name: /^Dining out/ })
    .click()
  await expect(page).toHaveURL(/category=/)
  await expect(transactionRows(page)).toHaveCount(5)
  await page.getByRole('combobox', { name: 'Month' }).selectOption('2026-08')
  await expect(page.getByText(/In August 2026 you saved/)).toBeVisible()
  await expect(page).toHaveURL(/month=2026-08/)
  await expect(page).toHaveURL(/category=/)
  await expect(transactionRows(page).first()).toContainText('Dining out')
  const august = await transactionRows(page).count()
  await page.reload()
  await expect(transactionRows(page)).toHaveCount(august)
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page).not.toHaveURL(/category=/)
})

test('sorting is announced with aria-sort, and a chart month can be picked', async ({ page }) => {
  await openSeptember(page)
  const amount = page.getByRole('columnheader', { name: /Amount/ })
  await expect(amount).toHaveAttribute('aria-sort', 'none')
  await amount.getByRole('button').click()
  await expect(amount).toHaveAttribute('aria-sort', 'descending')
  await expect(transactionRows(page).first()).toContainText('₹1,42,000.00')
  await page.getByRole('button', { name: /^July 2026: income/ }).click()
  await expect(page).toHaveURL(/month=2026-07/)
})

for (const scheme of ['light', 'dark'] as const) {
  test(`no accessibility violations (axe, ${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme })
    await openSeptember(page)
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze()
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.length} × ${v.help}`)).toEqual([])
  })
}

test('works at 400 px without horizontal scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 900 })
  await openSeptember(page)
  for (const path of [
    '/?month=2026-09',
    '/transactions?month=2026-09',
    '/review',
    '/settings/rules',
  ]) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, path).toBe(0)
  }
})

test('settings tabs have no accessibility violations (axe)', async ({ page }) => {
  for (const tab of ['budgets', 'categories', 'parsers', 'data']) {
    await page.goto(`/settings/${tab}`)
    await page.waitForLoadState('networkidle')
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
      .analyze()
    expect(results.violations.map((v) => `${tab}: ${v.id}: ${v.help}`)).toEqual([])
  }
})
