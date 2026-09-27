import { defineConfig, devices } from '@playwright/test';

const authStatePath = 'playwright/.auth/user.json';
const webPort = Number(process.env.PLAYWRIGHT_PORT || 4173);
if (!Number.isInteger(webPort) || webPort < 1024 || webPort > 65535) {
  throw new Error('PLAYWRIGHT_PORT must be an integer between 1024 and 65535.');
}

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    trace: 'on-first-retry',
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${webPort} --strictPort`,
    url: `http://127.0.0.1:${webPort}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'auth-setup',
      testDir: './e2e',
      testMatch: '**/auth_setup.spec.ts',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'chromium',
      dependencies: ['auth-setup'],
      use: { ...devices['Desktop Chrome'], storageState: authStatePath },
    },
    {
      name: 'e2e-ui',
      testDir: './tests/e2e-ui',
      dependencies: ['auth-setup'],
      use: { ...devices['Desktop Chrome'], storageState: authStatePath },
    },
    {
      name: 'ui-gadgets',
      testDir: './e2e',
      testIgnore: '**/auth_setup.spec.ts',
      dependencies: ['auth-setup'],
      use: { ...devices['Desktop Chrome'], storageState: authStatePath },
    },
  ],
});
