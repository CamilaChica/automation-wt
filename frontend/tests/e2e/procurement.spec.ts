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

test('authorized procurement users can inspect internal inventory and supplier profiles', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/inventory', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'INV-ADMIN-1',
      part_number: 'PN-100',
      serial_number: 'SN-100',
      quantity_available: 3,
      condition_code: 'NE',
      warehouse_location: 'MIA-A12',
      unit_cost: 1250,
      certificate_type: 'FAA 8130-3',
      has_full_trace: true,
    }]),
  }));
  await page.route('**/api/suppliers', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'SUP-ADMIN-1',
      company_name: 'Acme Components',
      contact_name: 'Morgan Lee',
      phone: '+1-555-0100',
      email: 'sales@acme.example',
      address_line1: '100 Aviation Way',
      city: 'Miami',
      state_province: 'FL',
      postal_code: '33101',
      country: 'US',
      approval_status: 'Approved',
      itar_certified: true,
    }]),
  }));
  await page.route('**/api/suppliers/SUP-ADMIN-1', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'SUP-ADMIN-1',
      company_name: 'Acme Components',
      contact_name: 'Morgan Lee',
      phone: '+1-555-0100',
      email: 'sales@acme.example',
      address_line1: '100 Aviation Way',
      city: 'Miami',
      state_province: 'FL',
      postal_code: '33101',
      country: 'US',
      approval_status: 'Approved',
      itar_certified: true,
    }),
  }));

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();

  await expect(page.getByRole('heading', { name: 'INVENTORY & SUPPLIER DIRECTORY' })).toBeVisible();
  await expect(page.getByText('PN-100', { exact: true })).toBeVisible();
  await expect(page.getByText('$1,250')).toBeVisible();
  await page.getByRole('tab', { name: 'Suppliers' }).click();
  await page.getByRole('button', { name: /Acme Components/ }).click();
  await expect(page.getByRole('heading', { name: 'Acme Components' })).toBeVisible();
  await expect(page.getByText('sales@acme.example')).toBeVisible();
});

test('sales role cannot load internal inventory or supplier directory', async ({ page }) => {
  let protectedRequests = 0;
  await page.addInitScript(() => {
    localStorage.setItem('wt_access_token', 'e2e-sales-token');
    localStorage.setItem('wt_role', 'ROLE_SALES');
    localStorage.setItem('wt_email', 'sales@example.com');
  });
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/inventory', route => {
    protectedRequests += 1;
    return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Insufficient permissions.' }) });
  });
  await page.route('**/api/suppliers**', route => {
    protectedRequests += 1;
    return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: 'Insufficient permissions.' }) });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();

  await expect(page.getByRole('heading', { name: 'INVENTORY & SUPPLIER DIRECTORY' })).toHaveCount(0);
  expect(protectedRequests).toBe(0);
});
