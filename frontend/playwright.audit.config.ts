import { defineConfig, devices } from '@playwright/test';

const auditPort = Number(process.env.PLAYWRIGHT_AUDIT_PORT || 4174);
if (!Number.isInteger(auditPort) || auditPort < 1024 || auditPort > 65535) {
  throw new Error('PLAYWRIGHT_AUDIT_PORT must be an integer between 1024 and 65535.');
}

export default defineConfig({
  testDir: './e2e/audit',
  timeout: 120_000,
  expect: { timeout: 7_500 },
  fullyParallel: true,
  workers: 1,
  retries: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: './test-results/audit-html-report', open: 'never' }],
  ],
  outputDir: './test-results/audit-artifacts',
  use: {
    baseURL: `http://127.0.0.1:${auditPort}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${auditPort} --strictPort`,
    url: `http://127.0.0.1:${auditPort}`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});