import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('admin interface audits logs and triggers hard freeze', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.goto('/');

  await page.getByRole('button', { name: 'AGENT LOGS' }).click();
  await expect(page.getByText('RFQIntakeAgent')).toBeVisible();
  await page.locator('div.fixed.inset-0.z-50 button').first().click();

  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();
  await expect(page.getByText('DOCUMENT REVIEW & VERIFICATION TERMINAL')).toBeVisible();
  await page.getByRole('button', { name: 'HARD FREEZE ORDER' }).click();

  await expect(
    page.getByText('Order hard freeze active: suspicious transaction blocked.')
  ).toBeVisible();
  await expect(page.getByText('Verification state: REVIEW_REQUIRED')).toBeVisible();
});
