import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('zero-human-in-the-loop autonomous flow across all interfaces', async ({ page }) => {
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
        rfq_id: 'WT-90002',
        status: 'Intake',
        message: 'RFQ accepted',
      }),
    });
  });
  await page.route('**/api/auth/otp/request', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ challenge_id: 'challenge-2', development_otp: '123456' }),
    });
  });
  await page.route('**/api/auth/otp/verify', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'token-customer',
        role: 'ROLE_CUSTOMER',
        email: 'mro.ops@globalairlines.com',
      }),
    });
  });

  await page.goto('/customer-portal');
  await page.getByLabel('Work email').fill('mro.ops@globalairlines.com');
  await page.getByRole('button', { name: 'Send one-time code' }).click();
  await page.getByPlaceholder('6-digit code').fill('123456');
  await page.getByRole('button', { name: 'Verify code' }).click();
  await expect(page.getByText('Customer parts portal')).toBeVisible();

  await page.getByPlaceholder('Company or contact name').fill('Global Airlines');
  await page.getByPlaceholder('Work email').fill('mro.ops@globalairlines.com');
  await page.getByPlaceholder('Part number', { exact: true }).fill('AOG-9981');
  await page.getByLabel('Quantity').fill('1');
  await page
    .getByPlaceholder('Condition, aircraft type, certification, delivery location...')
    .fill('AOG critical component. Need immediate dispatch with full ITAR docs.');
  await page.setInputFiles('input[type="file"]', {
    name: 'signed-export-compliance.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n%signed-export-compliance\n'),
  });
  await page.locator('input[type="checkbox"]').nth(1).check();
  await page.getByRole('button', { name: 'Send request' }).click();

  await expect.poll(() => intakeCalls).toBeGreaterThan(0);

  await seedSession(page, 'internal');
  await page.goto('/');

  await page.getByRole('button', { name: 'Sales Command' }).click();
  await page.getByRole('button', { name: 'ISSUE QUOTE' }).click();
  await expect(page.getByText(/issued to Global Airlines/i)).toBeVisible();

  await page.getByRole('button', { name: 'Proc Command' }).click();
  await expect(page.getByText('RFQ DETAIL & SOURCING')).toBeVisible();

  await page.getByRole('button', { name: 'Trace Vault' }).click();
  await expect(page.getByText('DOCUMENT REVIEW & VERIFICATION TERMINAL')).toBeVisible();
  await page.getByRole('button', { name: 'ACCEPT & CERTIFY' }).click();
  await expect(page.getByText('Verification state: CERTIFIED')).toBeVisible();
});
