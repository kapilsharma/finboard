import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { expect, type Page } from '@playwright/test'

export const PASSWORD = 'E2e-Statement-Pw'

export interface Fixture {
  path: string
  rows: number
  account_hint: string
  first_description: string
}

/** A synthetic, encrypted statement written to `dir`, a temp dir (never committed). */
export function makeFixture(dir: string, seed: number): Fixture {
  const path = join(dir, `statement-${seed}.pdf`)
  const out = execFileSync(
    'uv',
    ['run', '--project', resolve(__dirname, '../../backend'), 'python', 'make_fixture.py', path, PASSWORD, String(seed)],
    { cwd: resolve(__dirname, '..'), encoding: 'utf-8' },
  )
  return { path, ...JSON.parse(out) }
}

/** Upload the statement, type its password, and open the preview. */
export async function uploadAndUnlock(page: Page, path: string) {
  await page.goto('/import')
  await page.getByLabel('Choose PDF statements').setInputFiles(path)
  const item = page.getByRole('listitem').filter({ hasText: /statement-\d+\.pdf/ }).first()
  await expect(item.getByLabel('Statement password')).toBeVisible()
  await item.getByLabel('Statement password').fill(PASSWORD)
  await item.getByRole('button', { name: 'Unlock' }).click()
  await item.getByRole('link', { name: 'Review and commit' }).click()
}
