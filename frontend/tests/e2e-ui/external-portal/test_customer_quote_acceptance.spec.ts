import { expect, test } from '@playwright/test';
import { ExternalRFQPage } from '../pages/external-rfq.page';
import { seedCustomerSession } from '../fixtures/session';

test('submits a customer purchase order through the supported portal workflow', async ({ page }) => {
  let payload: unknown;
  await page.route('**/api/catalog/search**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/attachments', async route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ attachment_id: `ATT-${Date.now()}`, status: 'ACCEPTED' }) }));
  await page.route('**/api/purchase-orders', async route => {
    payload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'Purchase_Order_Received', po_number: 'PO-1001' }) });
  });
  await seedCustomerSession(page);
  const portal = new ExternalRFQPage(page);
  await portal.open();
  const form = portal.purchaseOrderForm();
  await form.getByPlaceholder('e.g., QTE-123456').fill('QTE-1001');
  await form.getByPlaceholder('e.g., PO-1001').fill('PO-1001');
  await form.getByPlaceholder('e.g., buyer@airline.com').fill('buyer@example.com');
  await form.locator('#po-export').setInputFiles({ name: 'export.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 export') });
  await form.locator('#po-kyc').setInputFiles({ name: 'kyc.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 kyc') });
  await form.locator('#po-document').setInputFiles({ name: 'po.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 po') });
  await form.getByRole('button', { name: 'Submit purchase order' }).click();
  await expect(page.getByText(/purchase order PO-1001 received/i)).toBeVisible();
  expect(payload).toMatchObject({ quote_id: 'QTE-1001', po_number: 'PO-1001', customer_email: 'buyer@example.com' });
  expect((payload as { attachment_ids: string[] }).attachment_ids).toHaveLength(3);
});