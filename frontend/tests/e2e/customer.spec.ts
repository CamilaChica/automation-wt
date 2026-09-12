import { expect, test } from '@playwright/test';

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
  await page.route('**/api/auth/otp/request', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ challenge_id: 'challenge-1', development_otp: '123456' }),
    });
  });
  await page.route('**/api/auth/otp/verify', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'token-customer',
        role: 'ROLE_CUSTOMER',
        email: 'procurement@delta-mro.com',
      }),
    });
  });

  await page.goto('/customer-portal');
  await page.getByLabel('Work email').fill('procurement@delta-mro.com');
  await page.getByRole('button', { name: 'Send one-time code' }).click();
  await page.getByPlaceholder('6-digit code').fill('123456');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await expect(page.getByText('Customer parts portal')).toBeVisible();
  await page.getByPlaceholder('Company or contact name').fill('Delta MRO Services');
  await page.getByPlaceholder('Work email').fill('procurement@delta-mro.com');
  await page.getByPlaceholder('Part number', { exact: true }).fill('AOG-9981');
  await page.getByLabel('Quantity').fill('1');
  await page
    .getByPlaceholder('Condition, aircraft type, certification, delivery location...')
    .fill('Urgent AOG request. Need factory-new with full export docs.');

  await page.setInputFiles('input[type="file"]', {
    name: 'euc.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%mock-euc\n'),
  });
  await page.locator('input[type="checkbox"]').nth(1).check();
  await page.getByRole('button', { name: 'Send request' }).click();

  await expect.poll(() => intakeCalls).toBeGreaterThan(0);
});
