import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('sales interface issues quote from automated workflow card', async ({ page }) => {
  await page.route('**/api/rfqs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 'WT-31005', customer_name: 'Global Airlines', status: 'Quoted' }]),
    });
  });
  await page.route('**/api/rfqs/WT-31005', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        rfq: { id: 'WT-31005', customer_name: 'Global Airlines', status: 'Quoted' },
        quote_details: { quote: { id: 'QTE-31005' }, items: [] },
        logs: [],
      }),
    });
  });
  await page.route('**/api/quotes/QTE-31005/approve', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'Quote_Sent' }) });
  });
  await seedSession(page, 'internal');
  await page.goto('/');

  await page.getByRole('button', { name: 'Sales Command' }).click();
  await expect(page.getByText('GLOBAL RFQ INBOX')).toBeVisible();
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();

  await expect(
    page.getByText(/Quote WT-31005 issued to Global Airlines/)
  ).toBeVisible();
});
