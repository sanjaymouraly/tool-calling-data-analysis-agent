import { defineConfig, devices } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 8000)
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`

/**
 * The end-to-end suite runs against the *production* build: the FastAPI
 * application serves the compiled React bundle, so the tests exercise the
 * same artefacts a user would run.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `python -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
        cwd: './backend',
        url: `${BASE_URL}/api/health`,
        reuseExistingServer: true,
        timeout: 120_000,
        env: {
          PYTHONPATH: './backend',
          SEED_DEMO_DATA_ON_STARTUP: 'true',
        },
      },
})
