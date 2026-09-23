import { expect, test } from '@playwright/test';
import { internalRfq, internalRfqDetail, automationEvent } from '../fixtures/mock_data';
import { seedCustomerSession, seedInternalSession } from '../fixtures/session';

test('customer submission is visible to staff through shared API state', async ({ browser }) => {
  const customer = await browser.newContext();
  const staff = await browser.newContext();
  const customerPage = await customer.newPage();
  const staffPage = await staff.newPage();
  await seedCustomerSession(customerPage);
  await seedInternalSession(staffPage);

  await customerPage.route('**/api/catalog/search**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await customerPage.route('**/api/rfqs/intake', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rfq_id: internalRfq.id, status: internalRfq.status, message: 'RFQ received' }) }));
  await customerPage.goto('/customer-portal');
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByPlaceholder('e.g., Global Airlines').fill('Global Airlines');
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByPlaceholder('e.g., buyer@airline.com').fill('buyer@example.com');
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByPlaceholder('e.g., BACB30LU-4').fill('XYZ123');
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByLabel('Quantity').fill('2');
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByLabel(/I confirm this order/).check();
  await customerPage.getByRole('form', { name: 'Request a quote form' }).getByRole('button', { name: 'Send request' }).click();

  await staffPage.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([internalRfq]) }));
  await staffPage.route(`**/api/rfqs/${internalRfq.id}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(internalRfqDetail) }));
  await staffPage.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([automationEvent]) }));
  await staffPage.goto('/');
  await staffPage.getByRole('button', { name: 'Sales Command' }).click();
  await expect(staffPage.getByRole('cell', { name: internalRfq.id })).toBeVisible();

  await customer.close();
  await staff.close();
});