import { defineConfig, devices } from '@playwright/test'

const PORT = process.env.E2E_SERVER_PORT ?? '8798'
const python = process.platform === 'win32' ? 'python' : 'python3'

/**
 * Server mode (FINBOARD_MODE=server, ADR-0041): the same stack as playwright.config.ts, started
 * with real sign-in and open sign-up, on its own port. Only tests/server-mode.spec.ts runs here.
 *
 *   npx playwright test -c playwright.server.config.ts
 */
export default defineConfig({
  testDir: './tests',
  testMatch: 'server-mode.spec.ts',
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
    env: {
      E2E_PORT: PORT,
      FINBOARD_MODE: 'server',
      FINBOARD_PUBLIC_URL: `http://127.0.0.1:${PORT}`,
      FINBOARD_SIGNUP: 'open',
    },
  },
})
