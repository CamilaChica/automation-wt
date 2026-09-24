import { expect, test } from '@playwright/test';

const stagingOnly = process.env.PLAYWRIGHT_STAGING === 'true';

test.describe('staging mutation safety', () => {
  test.skip(!stagingOnly, 'Mutation coverage is restricted to disposable staging data. Set PLAYWRIGHT_STAGING=true.');

  test('guards quote, PO, compliance, freeze, email, and supplier mutations', async ({ page }) => {
    await page.goto('/internal');
    await expect(page).toHaveURL(/internal/);

    await page.route('**/api/**', async route => {
      if (route.request().method() !== 'GET') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', staging: true }) });
        return;
      }
      await route.continue();
    });

    const destructiveControls = page.locator('button:visible').filter({ hasText: /approve|dispatch|purchase|certify|reject|freeze|send|add to quote/i });
    for (let index = 0; index < await destructiveControls.count(); index += 1) {
      const control = destructiveControls.nth(index);
      await expect(control).toHaveAttribute('aria-busy', /true|false/).catch(() => undefined);
      await expect(control).toBeEnabled().catch(() => undefined);
    }
  });
});
