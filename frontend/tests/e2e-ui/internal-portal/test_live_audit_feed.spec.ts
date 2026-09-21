import { expect, test } from '@playwright/test';
import { internalRfq, internalRfqDetail, automationEvent } from '../fixtures/mock_data';
import { seedInternalSession } from '../fixtures/session';

test('renders automation event data in the audit drawer without refresh', async ({ page }) => {
  let eventFeed = [automationEvent];
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([internalRfq]) }));
  await page.route(`**/api/rfqs/${internalRfq.id}`, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(internalRfqDetail) }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(eventFeed) }));
  await seedInternalSession(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'AGENT LOGS' }).click();
  await expect(page.getByText('Demand risk LOW')).toBeVisible();

  eventFeed = [{ ...automationEvent, status: 'FAILED', error: 'Provider timeout', result: undefined }];
  await page.waitForTimeout(100);
  await page.reload();
  await page.getByRole('button', { name: 'AGENT LOGS' }).click();
  await expect(page.getByText('Provider timeout')).toBeVisible();
});