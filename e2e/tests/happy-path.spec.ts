import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { makeFixture, uploadAndUnlock, type Fixture } from './helpers'

// The happy path of a first session: open the dashboard, import a password-protected statement,
// commit it, and find its transactions. It also runs against the packaged stack
// (scripts/smoke-compose.sh --e2e sets E2E_BASE_URL), which is the ROADMAP M7 acceptance row.
// Both stacks start with the synthetic demo data.

let dir: string
let fixture: Fixture

test.beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'finboard-e2e-'))
  fixture = makeFixture(dir, 7)
})

test.afterAll(() => rmSync(dir, { recursive: true, force: true }))

test('dashboard, then import a statement and find its transactions', async ({ page }) => {
  await page.goto('/?month=2026-09')
  await expect(page.getByText(/In September 2026 you saved/)).toBeVisible()
  await expect(page.getByRole('region', { name: 'Income', exact: true })).toContainText('₹1,42,702')

  // Upload → password → the worker parses it → preview → commit.
  await uploadAndUnlock(page, fixture.path)
  await expect(page.getByText('Balances reconcile')).toBeVisible()
  await expect(page.getByRole('table', { name: 'Preview' }).getByRole('row')).toHaveCount(
    fixture.rows + 1,
  )
  await page.getByRole('button', { name: `Commit ${fixture.rows} transactions` }).click()
  await expect(page.getByText(`${fixture.rows} transactions added to`)).toBeVisible()

  // The committed rows are in the ledger, and the import is in the history.
  await page.goto(`/transactions?q=${encodeURIComponent(fixture.first_description)}`)
  await expect(page.getByText(fixture.first_description).first()).toBeVisible()
  await page.goto('/settings/imports')
  await expect(page.getByRole('button', { name: /Roll back statement-7\.pdf/ })).toHaveCount(1)
})
