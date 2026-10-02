import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:3200", trace: "on-first-retry" },
  webServer: [
    { command: "node tests/e2e/mock_customer_api.cjs", url: "http://127.0.0.1:3210/healthz", reuseExistingServer: false, timeout: 120_000 },
    { command: "npm run dev -- --hostname 127.0.0.1 --port 3200", url: "http://127.0.0.1:3200", reuseExistingServer: false, timeout: 120_000, env: { API_BASE_URL: "http://127.0.0.1:3210", CUSTOMER_PORTAL_ORIGIN: "http://127.0.0.1:3200" } },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }, { name: "mobile", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true } }],
});
