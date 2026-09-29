import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('procurement interface supports supplier-matching workflow', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.goto('/');

  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await expect(page.getByText('RFQ DETAIL & SOURCING')).toBeVisible();
  await expect(page.getByText('SUPPLIER A', { exact: true })).toBeVisible();
  await page.getByText('SUPPLIER B', { exact: true }).first().click();
  await expect(page.getByText('ACTIVE RFQ QUEUE (SLA FOCUSED)')).toBeVisible();
});

test('procurement can process queued intake RFQs', async ({ page }) => {
  await seedSession(page, 'internal');
  let status = 'Intake';
  let processCalls = 0;

  await page.route('**/api/rfqs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'WT-PROCESS-1',
      customer_name: 'Process Test',
      customer_email: 'process@example.com',
      status,
      raw_text: 'Need one test part',
      created_at: new Date().toISOString(),
    }]),
  }));
  await page.route('**/api/supplier-offers**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/rfqs/WT-PROCESS-1/process', async route => {
    processCalls += 1;
    status = 'Validating';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status, message: 'RFQ processing started.' }),
    });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await page.getByRole('button', { name: 'PROCESS RFQ' }).click();

  await expect(page.getByRole('status').filter({ hasText: 'RFQ processing started.' })).toBeVisible();
  await expect.poll(() => processCalls).toBe(1);
  await expect(page.getByRole('button', { name: 'PROCESS RFQ' })).toHaveCount(0);
});

test('procurement does not offer retry for failed intake without a reset path', async ({ page }) => {
  await seedSession(page, 'internal');
  let processCalls = 0;

  await page.route('**/api/rfqs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'WT-FAILED-1',
      customer_name: 'Failed Test',
      customer_email: 'failed@example.com',
      status: 'Intake_Failed',
      raw_text: 'Unparseable test request',
      created_at: new Date().toISOString(),
    }]),
  }));
  await page.route('**/api/supplier-offers**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/rfqs/WT-FAILED-1/process', async route => {
    processCalls += 1;
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();

  await expect(page.getByText(/safe retry requires an intake reset/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'PROCESS RFQ' })).toHaveCount(0);
  expect(processCalls).toBe(0);
});
