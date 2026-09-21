import { expect, test } from '@playwright/test';
import { internalRfq, internalRfqDetail, automationEvent } from '../fixtures/mock_data';
import { seedInternalSession } from '../fixtures/session';

test('renders a live RFQ card and opens its operational detail flow', async ({ page }) => {
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([internalRfq]) }));
  await page.route(`**/api/rfqs/${internalRfq.id}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(internalRfqDetail) }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([automationEvent]) }));
  await seedInternalSession(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Sales Command' }).click();

  await expect(page.getByRole('cell', { name: internalRfq.id })).toBeVisible();
  await expect(page.getByText('XYZ123')).toBeVisible();
  await expect(page.getByText('Pending_Approval')).toBeVisible();
});