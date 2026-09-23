import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const rfqs = [
  {
    id: 'WT-29471',
    customer_name: 'GLOBAL AIRLINES',
    customer_email: 'mro.ops@globalairlines.com',
    status: 'Quoted',
    part_number: '32-11-45-01',
    quantity: 1,
    urgency: 'AOG',
    created_at: '2026-08-28T09:30:00Z',
  },
];

async function installApiRoutes(page: Page) {
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = [];

    if (path.endsWith('/rfqs')) body = rfqs;
    if (path.includes('/rfqs/') && request.method() === 'GET') {
      body = { ...rfqs[0], logs: [], quote_details: { quote: { id: 'QUOTE-1' } } };
    }
    if (path.endsWith('/catalog/search')) {
      body = [{ part_number: '32-11-45-01', condition_code: 'SV', quantity_available: 3, certificate_type: 'FAA 8130-3', has_full_trace: true }];
    }
    if (path.endsWith('/supplier-offers')) body = [];
    if (path.endsWith('/internal/shipments')) body = [];
    if (path.endsWith('/internal/automation-events')) body = [];
    if (path.endsWith('/attachments')) body = { attachment_id: 'ATT-E2E-00000000', filename: 'euc.pdf', status: 'ACCEPTED' };
    else if (request.method() === 'POST') body = { rfq_id: 'WT-SMOKE', status: 'Pending_Internal_Review', message: 'ok' };

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

async function assertNoRuntimeErrors(page: Page) {
  const errors = await page.evaluate(() => (window as Window & { __uiErrors?: string[] }).__uiErrors ?? []);
  expect(errors, 'uncaught browser errors').toEqual([]);
}

async function clickIfVisible(page: Page, name: string | RegExp) {
  const control = page.getByRole('button', { name }).first();
  if (await control.count() && await control.isVisible()) {
    await control.click();
  }
}

test.describe('UI gadget clickability', () => {
  test('crawls internal navigation, drawers, filters, and actions', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
      (window as Window & { __uiErrors?: string[] }).__uiErrors = [];
      window.addEventListener('error', event => {
        (window as Window & { __uiErrors?: string[] }).__uiErrors?.push(event.message);
      });
      window.addEventListener('unhandledrejection', event => {
        (window as Window & { __uiErrors?: string[] }).__uiErrors?.push(String(event.reason));
      });
    });
    await installApiRoutes(page);
    await page.goto('/internal');

    await clickIfVisible(page, 'Open audit log');
    await clickIfVisible(page, 'Close');

    for (const view of [/Sourcing Matrix/i, /Proc Command/i, /Trace Vault/i, /Fulfillment/i, /Sales Command/i, /Swarm Runner/i, /Dashboard/i]) {
      await page.getByRole('button', { name: view }).first().click();
      await expect(page.locator('main')).toBeVisible();
    }

    await page.getByRole('button', { name: /Sourcing Matrix/i }).first().click();
    for (const action of [/View Sourcing/i, /ADD TO QUOTE/i, /ISSUE PO/i, /DOC AUDIT/i, /Quick-Add/i]) {
      await clickIfVisible(page, action);
    }

    await page.getByRole('button', { name: /Proc Command/i }).first().click();
    for (const action of [/GENERATE SMART QUOTE/i, /SPLIT PO/i, /ESCALATE AOG/i]) {
      await clickIfVisible(page, action);
    }

    await page.getByRole('button', { name: /Fulfillment/i }).first().click();
    await clickIfVisible(page, /PRINT ATA 300/i);
    await clickIfVisible(page, /Toggle verified airworthiness/i);
    await clickIfVisible(page, /SERIALIZED TAMPER/i);

    await page.getByRole('button', { name: /Trace Vault/i }).first().click();
    for (const action of [/ACCEPT & CERTIFY/i, /REJECT DOC/i, /REQUEST RE-SCAN/i, /HARD FREEZE ORDER/i]) {
      await clickIfVisible(page, action);
    }

    await assertNoRuntimeErrors(page);
  });

  test('crawls customer search, attachment, RFQ, PO, and tracking controls', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_CUSTOMER');
      (window as Window & { __uiErrors?: string[] }).__uiErrors = [];
      window.addEventListener('error', event => {
        (window as Window & { __uiErrors?: string[] }).__uiErrors?.push(event.message);
      });
      window.addEventListener('unhandledrejection', event => {
        (window as Window & { __uiErrors?: string[] }).__uiErrors?.push(String(event.reason));
      });
    });
    await installApiRoutes(page);
    await page.goto('/customer-portal');

    await page.getByRole('button', { name: 'Search parts' }).click();
    await page.getByRole('button', { name: /32-11-45-01/ }).first().click();
    await page.getByLabel('Quantity').fill('2');
    await page.locator('input[type="file"]').setInputFiles({ name: 'euc.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') });
    await page.getByRole('checkbox').check();

    await page.getByPlaceholder('e.g., Global Airlines').fill('E2E Customer');
    await page.getByPlaceholder('e.g., buyer@airline.com').first().fill('e2e@example.com');
    await page.getByPlaceholder('e.g., BACB30LU-4').fill('32-11-45-01');
    await page.getByRole('button', { name: /Send request/i }).click();
    await expect(page.getByText(/Request WT-SMOKE received/i)).toBeVisible();

      await page.getByPlaceholder('e.g., QTE-123456').fill('QTE-E2E');
      await page.getByPlaceholder('e.g., PO-1001').fill('PO-E2E');
      await page.getByRole('button', { name: /Submit purchase order/i }).click();
    await expect(page.getByText(/Purchase order PO-E2E received/i)).toBeVisible();

      await page.getByPlaceholder('Enter your tracking token').fill('tracking-e2e');
    await page.getByRole('button', { name: 'Track shipment' }).click();
    await assertNoRuntimeErrors(page);
  });
});
