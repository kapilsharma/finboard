import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { makeFixture, uploadAndUnlock, type Fixture } from './helpers'

let dir: string
let fixture: Fixture

test.beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'finboard-e2e-'))
  fixture = makeFixture(dir, 4)
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
