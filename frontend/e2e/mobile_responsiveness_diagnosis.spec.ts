import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';

const internalTargets = [
  { path: '/internal', label: /Dashboard/i },
  { path: '/sales', label: /Sales Command/i },
  { path: '/sourcing', label: /Sourcing Matrix/i },
  { path: '/trace', label: /Trace Vault/i },
  { path: '/procurement', label: /Proc Command/i },
  { path: '/fulfillment', label: /Fulfillment/i },
];

const viewports = [
  { name: 'small-mobile', width: 375, height: 667 },
  { name: 'mobile-393', width: 393, height: 852 },
  { name: 'mobile-412', width: 412, height: 915 },
  { name: 'small-tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'wide-desktop', width: 2560, height: 1440 },
] as const;

const rfq = {
  id: 'RFQ-E2E-001',
  customer_name: 'E2E Aviation',
  customer_email: 'e2e@example.com',
  status: 'Quoted',
  part_number: '32-11-45-01',
  quantity: 1,
  urgency: 'Routine',
  created_at: '2026-08-28T09:30:00Z',
};

async function installApiRoutes(page: Page, status = rfq.status) {
  const responseRfq = { ...rfq, status };
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown = [];

    if (path.endsWith('/rfqs')) body = [responseRfq];
    else if (path.includes('/rfqs/') && request.method() === 'GET') {
      body = { ...responseRfq, logs: [], quote_details: { quote: { id: 'QTE-E2E-001' }, items: [] } };
    } else if (path.endsWith('/catalog/search')) {
      body = [{ part_number: rfq.part_number, condition_code: 'SV', quantity_available: 3, certificate_type: 'FAA 8130-3', has_full_trace: true }];
    } else if (path.endsWith('/supplier-offers')) {
      body = [];
    } else if (path.endsWith('/internal/shipments')) {
      body = [];
    } else if (path.endsWith('/internal/automation-events')) {
      body = [];
    } else if (path.endsWith('/attachments')) {
      body = { attachment_id: 'ATT-E2E-001', filename: 'euc.pdf', status: 'ACCEPTED' };
    } else if (request.method() !== 'GET') {
      body = { status: 'ok', message: 'Diagnostic request accepted.' };
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
}

test('failed intake disables quote, sourcing, and trace mutations', async ({ page }) => {
  await installErrorCapture(page);
  await installApiRoutes(page, 'Intake_Failed');
  await page.goto('/internal', { waitUntil: 'networkidle' });

  await selectTargetView(page, { path: '/sales', label: /Sales Command/i });
  await expect(page.getByRole('button', { name: 'ISSUE QUOTE' })).toBeDisabled();

  await selectTargetView(page, { path: '/procurement', label: /Proc Command/i });
  await expect(page.getByRole('button', { name: /GENERATE SMART QUOTE/i })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'SPLIT PO' })).toBeDisabled();

  await selectTargetView(page, { path: '/trace', label: /Trace Vault/i });
  await expect(page.getByRole('button', { name: /ACCEPT & CERTIFY/i })).toBeDisabled();
  await expect(page.getByRole('button', { name: /HARD FREEZE ORDER/i })).toBeDisabled();
});

test('cancelled quote and trace confirmations do not submit mutations', async ({ page }) => {
  const mutationRequests: string[] = [];
  const confirmationMessages: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/') && request.method() !== 'GET') mutationRequests.push(request.url());
  });
  page.on('dialog', async dialog => {
    confirmationMessages.push(dialog.message());
    await dialog.dismiss();
  });

  await installErrorCapture(page);
  await installApiRoutes(page);
  await page.goto('/internal', { waitUntil: 'networkidle' });
  await selectTargetView(page, { path: '/sales', label: /Sales Command/i });
  const issueQuote = page.getByRole('button', { name: 'ISSUE QUOTE' });
  await expect(issueQuote).toBeEnabled();
  await issueQuote.click();
  await expect.poll(() => confirmationMessages.length).toBe(1);

  await selectTargetView(page, { path: '/trace', label: /Trace Vault/i });
  const certify = page.getByRole('button', { name: /ACCEPT & CERTIFY/i });
  await expect(certify).toBeEnabled();
  await certify.click();
  await expect.poll(() => confirmationMessages.length).toBe(2);

  expect(confirmationMessages[0]).toContain('Issue quote');
  expect(confirmationMessages[1]).toContain('certify trace documents');
  expect(mutationRequests).toEqual([]);
});

test('shipment route displays the geographic map or its text fallback', async ({ page }) => {
  await installErrorCapture(page);
  await installApiRoutes(page);
  await page.goto('/internal', { waitUntil: 'networkidle' });
  await selectTargetView(page, { path: '/sourcing', label: /Sourcing Matrix/i });

  await expect.poll(async () => (
    await page.locator('.leaflet-container').count() > 0
    || await page.getByText(/Map tiles unavailable\. Demo routes:/).count() > 0
  )).toBe(true);
  await expect(page.getByText(/Demo route geometry only; carrier locations are not live\./)).toBeAttached();
  await expect(page.getByRole('link', { name: 'Map data: OpenStreetMap contributors' })).toBeAttached();
});

async function installErrorCapture(page: Page) {
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
}

async function selectTargetView(page: Page, target: typeof internalTargets[number]) {
  if (target.path === '/internal') return;
  const menuButton = page.getByRole('button', { name: 'Open navigation menu' });
  if (await menuButton.isVisible()) await menuButton.click();
  const navigation = page.getByRole('button', { name: target.label }).first();
  await expect(navigation, `Navigation control for ${target.path} is missing`).toBeVisible();
  await navigation.click();
}

async function collectDiagnostics(page: Page) {
  return page.evaluate(() => {
    const textClipping: string[] = [];
    const elements = Array.from(document.querySelectorAll<HTMLElement>('body *'));
    for (const element of elements) {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (element.children.length || !element.textContent?.trim() || !element.getClientRects().length || rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden') continue;
      if (element.scrollWidth > element.clientWidth + 1 && style.whiteSpace === 'nowrap' && style.textOverflow !== 'ellipsis' && !['hidden', 'auto', 'scroll'].includes(style.overflowX)) {
        textClipping.push(`${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}: ${element.textContent.trim().replace(/\s+/g, ' ').slice(0, 100)}`);
      }
    }

    const smallTouchTargets = Array.from(document.querySelectorAll<HTMLElement>('button, a, [role="button"], input, select, textarea'))
      .filter(element => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && (rect.width < 44 || rect.height < 44);
      })
      .map(element => `${element.tagName.toLowerCase()}[aria-label="${element.getAttribute('aria-label') || ''}"]: ${element.textContent?.trim().replace(/\s+/g, ' ').slice(0, 80) || ''}`);

    return {
      hasHorizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      overflowSources: elements
        .map(element => {
          const rect = element.getBoundingClientRect();
          return rect.right > window.innerWidth + 1
            ? `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}.${element.className.toString().split(/\s+/).slice(0, 3).join('.')}`
            : null;
        })
        .filter((value): value is string => Boolean(value))
        .slice(0, 30),
      textClipping,
      smallTouchTargets,
      uiErrors: (window as Window & { __uiErrors?: string[] }).__uiErrors || [],
    };
  });
}

async function attachDiagnostics(testInfo: TestInfo, targetPath: string, diagnostics: Awaited<ReturnType<typeof collectDiagnostics>>) {
  await testInfo.attach(`${targetPath.replace(/\W+/g, '-')}-diagnostics`, {
    body: JSON.stringify({ targetPath, ...diagnostics }, null, 2),
    contentType: 'application/json',
  });
}

for (const viewport of viewports) {
  test.describe(`${viewport.name} responsiveness`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const target of internalTargets) {
      test(`audits ${target.path} at ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
        await installErrorCapture(page);
        await installApiRoutes(page);
        await page.goto('/internal', { waitUntil: 'networkidle' });
        await selectTargetView(page, target);
        await page.waitForTimeout(250);

        const diagnostics = await collectDiagnostics(page);
        await attachDiagnostics(testInfo, target.path, diagnostics);
        expect(diagnostics.hasHorizontalOverflow, `Horizontal scroll detected on ${target.path} at ${viewport.width}x${viewport.height}`).toBe(false);
        expect(diagnostics.textClipping, `Text clipping detected on ${target.path}`).toEqual([]);
        expect(diagnostics.smallTouchTargets, `Touch targets below 44px detected on ${target.path}`).toEqual([]);
        expect(diagnostics.uiErrors, `Browser errors detected on ${target.path}`).toEqual([]);
      });
    }
  });
}
