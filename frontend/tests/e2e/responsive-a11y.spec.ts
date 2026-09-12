import { expect, test } from '@playwright/test';
import path from 'path';

const viewports = [
  { name: 'desktop', width: 1280, height: 720 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'mobile', width: 390, height: 844 },
];

const authenticateAdmin = async (page: import('@playwright/test').Page) => {
  await page.addInitScript(() => {
    localStorage.setItem('wt_access_token', 'e2e-token');
    localStorage.setItem('wt_email', 'admin@wingedtycoons.com');
    localStorage.setItem('wt_role', 'ROLE_ADMIN');
  });
};

for (const viewport of viewports) {
  test(`dashboard renders accessibly on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await authenticateAdmin(page);
    await page.goto('/');

    await expect(page.locator('header').first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Dashboard' })).toBeVisible();

    await page.addScriptTag({
      path: path.resolve(process.cwd(), 'node_modules', 'axe-core', 'axe.min.js'),
    });

    const accessibilityScan = await page.evaluate(async () => {
      const axe = (window as typeof window & { axe: { run: (ctx: Document, opts: unknown) => Promise<{ violations: Array<{ impact: string | null }> }> } }).axe;
      return axe.run(document, {
        runOnly: {
          type: 'tag',
          values: ['wcag2a', 'wcag2aa'],
        },
      });
    });

    const criticalViolations = accessibilityScan.violations.filter(
      violation => violation.impact === 'critical',
    );
    expect(criticalViolations).toEqual([]);

    const screenshot = await page.screenshot({ fullPage: true });
    await testInfo.attach(`dashboard-${viewport.name}.png`, {
      body: screenshot,
      contentType: 'image/png',
    });
  });
}
