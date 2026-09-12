import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('procurement interface supports supplier-matching workflow', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.goto('/');

  await page.getByRole('button', { name: 'Proc Command' }).click();
  await expect(page.getByText('RFQ DETAIL & SOURCING')).toBeVisible();
  await expect(page.getByText('SUPPLIER A')).toBeVisible();
  await page.getByText('SUPPLIER B').click();
  await expect(page.getByText('ACTIVE RFQ QUEUE (SLA FOCUSED)')).toBeVisible();
});
