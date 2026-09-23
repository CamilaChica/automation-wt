import { expect, test } from '@playwright/test';
import { ExternalRFQPage } from '../pages/external-rfq.page';
import { seedCustomerSession } from '../fixtures/session';

test('submits a customer RFQ through the supported external portal', async ({ page }) => {
  await page.route('**/api/catalog/search**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/rfqs/intake', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rfq_id: 'RFQ-EXT-001', status: 'Pending_Approval', message: 'RFQ received' }) }));
  await seedCustomerSession(page);
  const portal = new ExternalRFQPage(page);
  await portal.open();
  await portal.submitRfq();
  await expect(page.getByText(/RFQ-EXT-001 received/)).toBeVisible();
});

test('blocks malformed customer input before submission', async ({ page }) => {
  let intakeCalled = false;
  await page.route('**/api/catalog/search**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/rfqs/intake', async route => {
    intakeCalled = true;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await seedCustomerSession(page);
  const portal = new ExternalRFQPage(page);
  await portal.open();
  const form = portal.quoteForm();
  await form.getByPlaceholder('e.g., Global Airlines').fill('Global Airlines');
  await form.getByPlaceholder('e.g., buyer@airline.com').fill('not-an-email');
  await form.getByPlaceholder('e.g., BACB30LU-4').fill('XYZ123');
  await form.getByLabel('Quantity').fill('0');
  await form.getByLabel(/I confirm this order/).check();
  await form.getByRole('button', { name: 'Send request' }).click();

  await expect(form.getByPlaceholder('e.g., buyer@airline.com')).toHaveAttribute('type', 'email');
  await expect(form.getByLabel('Quantity')).toHaveAttribute('min', '1');
  expect(intakeCalled).toBe(false);
});