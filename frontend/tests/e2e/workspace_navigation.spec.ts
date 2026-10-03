import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('wt_role', 'ROLE_MANAGER');
    localStorage.setItem('wt_email', 'operator@example.test');
    document.cookie = 'wt_internal_view=customer; Path=/';
  });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) {
      return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
    }
    let body: unknown = [];
    if (url.pathname === '/api/internal/profile') {
      body = { email: 'operator@example.test', display_name: 'Test Operator', job_title: 'Manager', is_online: true };
    } else if (url.pathname === '/api/internal/sales/me') {
      body = { month: '2026-10', revenue: 100, orders: 1, hours: 2, daily_seconds: {}, handled_rfqs: [] };
    } else if (url.pathname === '/api/internal/sales/leaderboard') {
      body = { month: '2026-10', board: [] };
    } else if (url.pathname === '/api/internal/work-hours') {
      body = { month: '2026-10', total_seconds: 7200, daily_seconds: {} };
    } else if (url.pathname === '/api/internal/hr/work-hours') {
      body = { month: '2026-10', employees: [] };
    } else if (url.pathname.includes('/mailboxes/')) {
      body = { messages: [] };
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
});

test('combines shipments and map in one workspace', async ({ page }) => {
  await page.goto('/internal');
  const sidebar = page.locator('aside');
  await expect(sidebar.getByRole('button', { name: 'Shipments Map', exact: true })).toHaveCount(0);
  await sidebar.getByRole('button', { name: 'Shipments', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Shipments & Tracking', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Map', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Shipments map', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Orders & Tracking', exact: true }).click();
  await expect(page.getByText('ORDER INGEST', { exact: true })).toBeVisible();
});

test('combines sales, hours and profile, and leaderboard without a separate drawer', async ({ page }) => {
  await page.goto('/internal');
  await page.locator('aside').getByRole('button', { name: 'My Work', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'My sales', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Hours & Profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your profile & hours', exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Team Leaderboard', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sales race', exact: true })).toBeVisible();
  await expect(page.locator('aside').getByRole('button', { name: 'Sales Race', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open employee profile and work hours', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your profile & hours', exact: true })).toBeVisible();
});

test('removes the logo border and explains purchase orders without a fake action', async ({ page }) => {
  await page.goto('/internal');
  const logo = page.getByRole('link', { name: 'Winged Tycoons Executive Dashboard' });
  await expect(logo).toHaveCSS('border-top-width', '0px');
  await page.locator('aside').getByRole('button', { name: 'Supplier Offers', exact: true }).click();
  await expect(page.getByRole('button', { name: 'ISSUE PO', exact: true })).toHaveCount(0);
  await expect(page.getByText('Customers submit purchase orders through the customer portal after receiving a quote.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open RFQ Reviews', exact: true })).toBeDisabled();
});

test('opens actual RFQ reviews from sourcing without recording a fake audit', async ({ page }) => {
  const rfq = (id: string) => ({
    id, customer_name: 'Test MRO', customer_email: 'buyer@example.test',
    status: 'Supplier_Sourcing', raw_text: 'Need one actuator',
    created_at: '2026-10-03T14:00:00Z', part_number: 'ACT-100', quantity: 1,
  });
  await page.route('**/api/rfqs', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify([rfq('RFQ-FIRST'), rfq('RFQ-SELECTED')]),
  }));
  const commands: string[] = [];
  page.on('request', request => {
    if (request.method() === 'POST') commands.push(request.url());
  });
  await page.goto('/internal');
  await page.locator('aside').getByRole('button', { name: 'Supplier Offers', exact: true }).click();
  await page.getByRole('row').filter({ hasText: 'RFQ-SELECTED' }).getByRole('button', { name: 'View Sourcing' }).click();
  await page.getByRole('button', { name: 'Open RFQ Reviews', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Selected RFQ: RFQ-SELECTED' })).toBeVisible();
  expect(commands).toEqual([]);
});

test('keeps grouped sections usable at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto('/internal');
  await page.getByRole('button', { name: 'Open navigation menu' }).click();
  await page.locator('aside').getByRole('button', { name: 'My Work', exact: true }).click();
  const sections = page.getByRole('navigation', { name: 'My work sections' });
  await expect(sections).toBeVisible();
  await sections.getByRole('button', { name: 'Hours & Profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your profile & hours', exact: true })).toBeVisible();
  const buttons = await sections.getByRole('button').all();
  for (const button of buttons) {
    const box = await button.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height).toBeGreaterThanOrEqual(44);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(375);
  }
});
