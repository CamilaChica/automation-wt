import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('sales interface issues quote from automated workflow card', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.goto('/');

  await page.getByRole('button', { name: 'Sales Command' }).click();
  await expect(page.getByText('GLOBAL RFQ INBOX')).toBeVisible();
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();

  await expect(
    page.getByText(/Quote WT-31005 issued to Global Airlines/)
  ).toBeVisible();
});
