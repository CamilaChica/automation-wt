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
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();

  await expect(
    page.getByText(/Quote WT-31005 issued to Global Airlines/)
  ).toBeVisible();
});

test('sales can reject a quote with an audited reason', async ({ page }) => {
  let rfqStatus = 'Quoted';
  let rejectionPayload: { operator_name: string; comments: string } | undefined;

  await page.route('**/api/rfqs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 'WT-REJECT-1', customer_name: 'Global Airlines', status: rfqStatus }]),
    });
  });
  await page.route('**/api/rfqs/WT-REJECT-1', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        rfq: { id: 'WT-REJECT-1', customer_name: 'Global Airlines', status: rfqStatus },
        quote_details: { quote: { id: 'QTE-REJECT-1' }, items: [] },
        logs: [],
      }),
    });
  });
  await page.route('**/api/quotes/QTE-REJECT-1/reject', async route => {
    rejectionPayload = route.request().postDataJSON();
    rfqStatus = 'Rejected';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'Rejected', quote_id: 'QTE-REJECT-1' }),
    });
  });
  await seedSession(page, 'internal');
  await page.goto('/');
  await page.getByRole('button', { name: 'Sales Command' }).click();

  await page.getByLabel('Reason for quote rejection').fill('Supplier cannot meet the required delivery date.');
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'REJECT QUOTE' }).click();

  await expect(page.getByText('Quote rejected.', { exact: true })).toBeVisible();
  await expect.poll(() => rejectionPayload).toEqual({
    operator_name: 'camila@wingedtycoons.com',
    comments: 'Supplier cannot meet the required delivery date.',
  });
  await expect(page.getByRole('button', { name: 'REJECT QUOTE' })).toBeDisabled();
});
