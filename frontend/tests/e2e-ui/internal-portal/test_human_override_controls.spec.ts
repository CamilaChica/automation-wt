import { expect, test } from '@playwright/test';
import { internalRfq, internalRfqDetail, automationEvent } from '../fixtures/mock_data';
import { seedInternalSession } from '../fixtures/session';

test('approves a quote with an explicit override payload', async ({ page }) => {
  let approvalPayload: unknown;
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([internalRfq]) }));
  await page.route(`**/api/rfqs/${internalRfq.id}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(internalRfqDetail) }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([automationEvent]) }));
  await page.route('**/api/quotes/QTE-UI-001/approve', async route => {
    approvalPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'Quote_Sent' }) });
  });
  await seedInternalSession(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Sales Command' }).click();
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();

  await expect(page.getByText(/issued to Global Airlines/i)).toBeVisible();
  expect(approvalPayload).toMatchObject({
    operator_name: 'Alex R. (Sales Lead)',
    items_override: [{ quote_item_id: 'QITEM-01', unit_price: 14200 }],
  });
});