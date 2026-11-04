import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const PASSWORD = 'E2e-Statement-Pw'

interface Fixture {
  path: string
  rows: number
  account_hint: string
  first_description: string
}

let dir: string
let fixture: Fixture

/** A synthetic, encrypted statement written to a temp dir (never committed). */
function makeFixture(seed: number): Fixture {
  const path = join(dir, `statement-${seed}.pdf`)
  const out = execFileSync(
    'uv',
    ['run', '--project', resolve(__dirname, '../../backend'), 'python', 'make_fixture.py', path, PASSWORD, String(seed)],
    { cwd: resolve(__dirname, '..'), encoding: 'utf-8' },
  )
  return { path, ...JSON.parse(out) }
}

async function uploadAndUnlock(page: Page, path: string) {
  await page.goto('/import')
  await page.getByLabel('Choose PDF statements').setInputFiles(path)
  const item = page.getByRole('listitem').filter({ hasText: /statement-\d+\.pdf/ }).first()
  await expect(item.getByLabel('Statement password')).toBeVisible()
  await item.getByLabel('Statement password').fill(PASSWORD)
  await item.getByRole('button', { name: 'Unlock' }).click()
  await item.getByRole('link', { name: 'Review and commit' }).click()
}

test.beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'finboard-e2e-'))
  fixture = makeFixture(4)
})

test.afterAll(() => rmSync(dir, { recursive: true, force: true }))

test('upload an encrypted statement, unlock it, commit, and re-import nothing', async ({
  page,
}) => {
  await uploadAndUnlock(page, fixture.path)

  // Preview: reconciles, shows the rows, and suggests an account for the unknown card number.
  await expect(page.getByText('Balances reconcile')).toBeVisible()
  const preview = page.getByRole('table', { name: 'Preview' })
  await expect(preview.getByRole('row')).toHaveCount(fixture.rows + 1)
  await expect(preview.getByText(fixture.first_description).first()).toBeVisible()
  await expect(page.getByLabel('New account name')).toHaveValue(new RegExp(fixture.account_hint))

  await page.getByRole('button', { name: `Commit ${fixture.rows} transactions` }).click()
  await expect(page.getByText(`${fixture.rows} transactions added to`)).toBeVisible()

  // The same statement again: every row is already imported.
  await uploadAndUnlock(page, fixture.path)
  await expect(page.getByText('You already imported this exact file')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Summary' })).toContainText('0 new')
  await expect(page.getByText(`${fixture.rows} already imported`)).toBeVisible()
  await page.getByRole('button', { name: 'Commit 0 transactions' }).click()
  await expect(page.getByText(`0 transactions added to`)).toBeVisible()

  // Import history lists both.
  await page.goto('/settings/imports')
  await expect(page.getByRole('button', { name: /Roll back statement-4\.pdf/ })).toHaveCount(2)
})
