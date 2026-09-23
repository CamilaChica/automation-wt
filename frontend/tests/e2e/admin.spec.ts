import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('admin interface audits logs and triggers hard freeze', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'WT-ADMIN-1', customer_name: 'Admin Test', customer_email: 'admin@example.com', status: 'Quoted', raw_text: 'test', created_at: new Date().toISOString() }]) }));
  await page.route('**/api/internal/rfqs/*/trace-decision', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ decision: 'freeze', automation_paused: true }) }));
  await page.goto('/');

  await page.getByRole('button', { name: 'AGENT LOGS' }).click();
  await expect(page.getByText('RFQIntakeAgent')).toBeVisible();
  await page.locator('div.fixed.inset-0.z-50 button').first().click();

  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();
  await expect(page.getByText('DOCUMENT REVIEW & VERIFICATION TERMINAL')).toBeVisible();
  await page.getByRole('button', { name: 'HARD FREEZE ORDER' }).click();

  await expect(page.getByText(/Trace decision freeze recorded|Order hard freeze active/).first()).toBeVisible();
  await expect(page.getByText('Verification state: REVIEW_REQUIRED')).toBeVisible();
});
