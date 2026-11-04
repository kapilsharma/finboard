import { defineConfig, devices } from '@playwright/test'

const PORT = process.env.E2E_PORT ?? '8799'
const python = process.platform === 'win32' ? 'python' : 'python3'

/**
 * End-to-end tests against `finboard serve` + a worker (see stack.py), on the `finboard_test`
 * database. Prerequisites: Postgres + Redis (deploy/compose.dev.yaml), `uv` on PATH, and the
 * SPA built (`npm run build` in frontend/).
 *
 * E2E_CHROMIUM_PATH points at an already-installed Chromium instead of Playwright's own (e.g. a
 * sandbox with a preinstalled browser of another Playwright version). Unset in CI.
 */
export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          executablePath: process.env.E2E_CHROMIUM_PATH || undefined,
        },
      },
    },
  ],
  webServer: {
    command: `${python} stack.py`,
    url: `http://127.0.0.1:${PORT}/api/v1/health/ready`,
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: 'pipe',
    stderr: 'pipe',
    env: { E2E_PORT: PORT },
  },
})
