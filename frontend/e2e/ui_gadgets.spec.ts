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
  await page.route('**/ready', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ status: 'ready', database: { healthy: true }, persistence: { storage_engine: 'postgresql' } }),
  }));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = [];

    if (path.endsWith('/rfqs')) body = rfqs;
    if (path.includes('/rfqs/') && request.method() === 'GET') {
      body = { ...rfqs[0], logs: [], quote_details: { quote: { id: 'QUOTE-1', total_amount: 14450 } } };
    }
    if (path.endsWith('/catalog/search')) {
      body = [{ part_number: '32-11-45-01', condition_code: 'SV', quantity_available: 3, certificate_type: 'FAA 8130-3', has_full_trace: true }];
    }
    if (path.endsWith('/supplier-offers')) body = [];
    if (path.endsWith('/internal/shipments')) body = [{ id: 'SHIP-E2E-001', status: 'IN_TRANSIT', carrier: 'E2E Carrier', tracking_number: 'TRACK-E2E-001' }];
    if (path.endsWith('/internal/automation-events')) body = [];
    if (path.endsWith('/internal/mailboxes/health')) body = { sales_mailbox: 'ok', purchasing_mailbox: 'ok', authenticated_user: 'e2e@example.test' };
    if (path.endsWith('/rfqs/intake')) body = { rfq_id: 'WT-SMOKE', status: 'Pending_Internal_Review', message: 'Request WT-SMOKE received.' };
    else if (path.endsWith('/attachments')) body = { attachment_id: 'ATT-E2E-00000000', filename: 'euc.pdf', status: 'ACCEPTED' };
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
  test('header binds live readiness and mailbox health', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
    });
    await installApiRoutes(page);
    await page.goto('/internal', { waitUntil: 'networkidle' });
    await expect(page.getByText('API READY')).toBeVisible();
    await expect(page.getByText('MAIL OK')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open notifications and agent activity' })).toBeVisible();
  });

  test('trace mutation invalidates live RFQ and event queries', async ({ page }) => {
    let eventReads = 0;
    let traceDecisions = 0;
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
    });
    await installApiRoutes(page);
    await page.route('**/api/internal/automation-events**', async route => {
      eventReads += 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    });
    await page.route('**/api/internal/rfqs/*/trace-decision**', async route => {
      traceDecisions += 1;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ decision: 'certify', automation_paused: false }) });
    });
    page.on('dialog', dialog => dialog.accept());
    await page.goto('/internal', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: /Trace Vault/i }).first().click();
    await expect(page.getByRole('button', { name: /ACCEPT & CERTIFY/i })).toBeEnabled();
    await expect.poll(() => eventReads).toBeGreaterThan(0);
    const initialEventReads = eventReads;
    await page.getByRole('button', { name: /ACCEPT & CERTIFY/i }).click();
    await expect.poll(() => traceDecisions).toBe(1);
    await expect.poll(() => eventReads).toBeGreaterThan(initialEventReads);
  });

  test('Network error and state degradation handles gracefully', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
      (window as Window & { __uiErrors?: string[] }).__uiErrors = [];
      window.addEventListener('error', event => {
        (window as Window & { __uiErrors?: string[] }).__uiErrors?.push(event.message);
      });
    });
    let unauthenticatedAuthorization: string | undefined;
    await page.route('**/api/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path.endsWith('/internal/commands')) {
        unauthenticatedAuthorization = request.headers().authorization;
        await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Authentication required.' }) });
      } else if (path.endsWith('/rfqs') || path.endsWith('/internal/shipments')) {
        await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Diagnostic service unavailable.' }) });
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      }
    });
    await page.goto('/internal', { waitUntil: 'networkidle' });

    const unavailable = page.getByText('Service temporarily unavailable (HTTP 503). Please retry.').first();
    await expect(unavailable).toBeVisible();
    await page.getByRole('button', { name: /Fulfillment/i }).first().click();
    await expect(page.getByRole('alert').filter({ hasText: 'Service temporarily unavailable (HTTP 503)' }).first()).toBeVisible();
    await expect(page.getByText('SAMPLE / DEMO DATA', { exact: true }).first()).toBeVisible();
    await expect(page.locator('main')).toBeVisible();

    const unauthorizedStatus = await page.evaluate(async () => (await fetch('/api/internal/commands', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'print_tags', entity_id: 'SHIP-E2E-001' }),
    })).status);
    expect(unauthorizedStatus).toBe(401);
    expect(unauthenticatedAuthorization).toBeUndefined();
    await assertNoRuntimeErrors(page);
  });

  test('customer PO dispatch remains single-submit while pending', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', 'ROLE_ADMIN');
    });
    await installApiRoutes(page);
    let releasePurchaseOrder: (() => void) | undefined;
    let dispatchRequests = 0;
    await page.route('**/api/quotes/QUOTE-1/approve', async route => {
      dispatchRequests += 1;
      await new Promise<void>(resolve => { releasePurchaseOrder = resolve; });
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'Sent', quote_id: 'QUOTE-1', message: 'Quote QUOTE-1 dispatched.' }) });
    });
    await page.goto('/internal', { waitUntil: 'networkidle' });

    const openApproval = page.getByRole('button', { name: /APPROVE & DISPATCH QUOTE/i });
    await expect(openApproval).toBeEnabled();
    await openApproval.click();
    const dispatch = page.getByRole('button', { name: 'CONFIRM & DISPATCH QUOTE' });
    await dispatch.click();
    await expect.poll(() => dispatchRequests).toBe(1);

    const pendingDispatch = page.getByRole('button', { name: 'DISPATCHING...' });
    await expect(pendingDispatch).toBeDisabled();
    await expect(pendingDispatch).toHaveAttribute('aria-busy', 'true');
    const approverInputDisabled = await page.locator('input').evaluateAll(inputs =>
      inputs.find(input => (input as HTMLInputElement).value === 'Alex R. (Lead MRO Engineer)')?.disabled,
    );
    expect(approverInputDisabled).toBe(true);
    expect(dispatchRequests).toBe(1);

    releasePurchaseOrder?.();
    await expect(page.getByRole('heading', { name: 'Confirm Quote Approval and Dispatch' })).not.toBeVisible();
    await expect(page.getByRole('status').filter({ hasText: 'Quote QUOTE-1 dispatched.' })).toBeVisible();
  });

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

    await clickIfVisible(page, 'Open notifications and agent activity');
    await clickIfVisible(page, 'Close');

    for (const view of [/Sourcing Matrix/i, /Proc Command/i, /Trace Vault/i, /Fulfillment/i, /Sales Command/i, /Swarm Runner/i, /Dashboard/i]) {
      await page.getByRole('button', { name: view }).first().click();
      await expect(page.locator('main')).toBeVisible();
    }

    await page.getByRole('button', { name: /Swarm Runner/i }).first().click();
    const runCount = page.getByText(/^\d+ runs$/);
    await expect(runCount).toHaveCSS('align-items', 'center');
    await expect(runCount).toHaveCSS('height', '28px');

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

    await page.getByRole('textbox', { name: 'Search aircraft parts' }).fill('32-11-45-01');
    await page.getByRole('button', { name: 'Search parts' }).click();
    await page.getByRole('button', { name: /32-11-45-01/ }).first().click();
    await page.getByRole('spinbutton', { name: 'Quantity' }).fill('2');
    await page.locator('#compliance-file').setInputFiles({ name: 'parts-list.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') });
    await page.getByRole('checkbox').check();

    await page.getByPlaceholder('e.g., Global Airlines').fill('E2E Customer');
    await page.getByPlaceholder('e.g., buyer@airline.com').first().fill('e2e@example.com');
    await page.getByPlaceholder('e.g., BACB30LU-4').fill('32-11-45-01');
    await page.getByLabel('Target condition').selectOption({ label: 'OH - Overhauled' });
    await page.getByRole('button', { name: /Send request/i }).click();
    await expect(page.getByText(/Request WT-SMOKE received/i)).toBeVisible();

      await page.getByPlaceholder('e.g., QTE-123456').fill('QTE-E2E');
      await page.getByPlaceholder('e.g., PO-1001').fill('PO-E2E');
      const compliancePdf = { name: 'euc.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4') };
      await page.locator('#po-export').setInputFiles(compliancePdf);
      await page.locator('#po-kyc').setInputFiles(compliancePdf);
      await page.locator('#po-document').setInputFiles(compliancePdf);
      await page.getByRole('button', { name: /Submit purchase order/i }).click();
    await expect(page.getByText(/Purchase order PO-E2E received/i)).toBeVisible();

      await page.getByPlaceholder('Enter your tracking token').fill('tracking-e2e');
    await page.getByRole('button', { name: 'Track a shipment' }).click();
    await assertNoRuntimeErrors(page);
  });
});
