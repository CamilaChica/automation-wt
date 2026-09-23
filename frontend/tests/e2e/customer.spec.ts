import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('customer uploads compliance PDF and submits urgent request', async ({ page }) => {
  let intakeCalls = 0;
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
  await page.route('**/api/attachments', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ attachment_id: 'ATT-E2E-1', filename: 'euc.pdf', status: 'ACCEPTED' }) }));
  await page.route('**/api/rfqs/intake', async route => {
    intakeCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        rfq_id: 'WT-90001',
        status: 'Intake',
        message: 'RFQ accepted',
      }),
    });
  });
  await seedSession(page, 'customer');
  await page.goto('/customer-portal');
  await expect(page.getByText('Customer parts portal')).toBeVisible();
  const quoteForm = page.getByRole('form', { name: 'Request a quote form' });
  await page.getByPlaceholder('e.g., Global Airlines').fill('Delta MRO Services');
  await quoteForm.getByPlaceholder('e.g., buyer@airline.com').fill('procurement@delta-mro.com');
  await quoteForm.getByPlaceholder('e.g., BACB30LU-4').fill('AOG-9981');
  await quoteForm.getByLabel('Quantity').fill('1');
  await page
    .getByPlaceholder('Condition, aircraft type, certification, and delivery location')
    .fill('Urgent AOG request. Need factory-new with full export docs.');

  await page.setInputFiles('input[type="file"]', {
    name: 'euc.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%mock-euc\n'),
  });
  await page
    .getByLabel(/I confirm this order and compliance documentation are valid for export screening\./)
    .check();
  await page.getByRole('button', { name: 'Send request' }).click();

  await expect.poll(() => intakeCalls).toBeGreaterThan(0);
});
