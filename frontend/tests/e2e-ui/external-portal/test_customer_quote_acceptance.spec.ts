import { expect, test } from '@playwright/test';
import { ExternalRFQPage } from '../pages/external-rfq.page';
import { seedCustomerSession } from '../fixtures/session';

test('submits a customer purchase order through the supported portal workflow', async ({ page }) => {
  let payload: unknown;
  await page.route('**/api/catalog/search**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/purchase-orders', async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'Purchase_Order_Received', po_number: 'PO-1001' }) });
  });
  await seedCustomerSession(page);
  const portal = new ExternalRFQPage(page);
  await portal.open();
  const form = portal.purchaseOrderForm();
  await form.getByPlaceholder(/Quote reference/).fill('QTE-1001');
  await form.getByPlaceholder(/purchase order number/).fill('PO-1001');
  await form.getByPlaceholder('Work email').fill('buyer@example.com');
  await form.getByRole('button', { name: 'Submit purchase order' }).click();
  await expect(page.getByText(/purchase order PO-1001 received/i)).toBeVisible();
  expect(payload).toEqual({ quote_id: 'QTE-1001', po_number: 'PO-1001', customer_email: 'buyer@example.com' });
});