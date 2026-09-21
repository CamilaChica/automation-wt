import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('zero-human-in-the-loop autonomous flow across all interfaces', async ({ page }) => {
  let intakeCalls = 0;
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
  await page.route('**/api/catalog/search**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          part_number: 'AOG-9981',
          condition_code: 'FN',
          quantity_available: 2,
          certificate_type: 'FAA 8130-3',
          has_full_trace: true,
        },
      ]),
    });
  });
  await page.route('**/api/rfqs/intake', async route => {
    intakeCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        rfq_id: 'WT-90002',
        status: 'Intake',
        message: 'RFQ accepted',
      }),
    });
  });
  await seedSession(page, 'customer');
  await page.goto('/customer-portal');
  await expect(page.getByText('Customer parts portal')).toBeVisible();
  const quoteForm = page.getByRole('form', { name: 'Request a quote form' });

  await page.getByPlaceholder('Company or contact name').fill('Global Airlines');
  await quoteForm.getByPlaceholder('Work email').fill('mro.ops@globalairlines.com');
  await quoteForm.getByPlaceholder('Part number', { exact: true }).fill('AOG-9981');
  await quoteForm.getByLabel('Quantity').fill('1');
  await page
    .getByPlaceholder('Condition, aircraft type, certification, delivery location...')
    .fill('AOG critical component. Need immediate dispatch with full ITAR docs.');
  await page.setInputFiles('input[type="file"]', {
    name: 'signed-export-compliance.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%signed-export-compliance\n'),
  });
  await page
    .getByLabel(/I confirm this order and compliance documentation are valid for export screening\./)
    .check();
  await page.getByRole('button', { name: 'Send request' }).click();

  await expect.poll(() => intakeCalls).toBeGreaterThan(0);

  await seedSession(page, 'internal');
  await page.goto('/');

  await page.locator('aside button').filter({ hasText: 'Sales Command' }).first().click();
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();
  await expect(page.getByText(/issued to Global Airlines/i)).toBeVisible();

  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await expect(page.getByText('RFQ DETAIL & SOURCING')).toBeVisible();

  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();
  await expect(page.getByText('DOCUMENT REVIEW & VERIFICATION TERMINAL')).toBeVisible();
  await page.getByRole('button', { name: 'ACCEPT & CERTIFY' }).click();
  await expect(page.getByText('Verification state: CERTIFIED')).toBeVisible();
});
