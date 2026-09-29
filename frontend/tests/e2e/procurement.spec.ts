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

test('authorized users can request freight rates and distinguish a dry run', async ({ page }) => {
  await seedSession(page, 'internal');
  let freightRequest: Record<string, unknown> | undefined;
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/inventory', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/suppliers', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/freight/quote', async route => {
    freightRequest = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        provider: 'configured-carrier-api',
        status: 'DRY_RUN',
        request: freightRequest,
        rates: [],
        message: 'Freight provider is disabled; the shipping charge was not added to the customer quote.',
      }),
    });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await page.getByLabel('Freight origin').fill('MIA');
  await page.getByLabel('Freight destination').fill('JFK');
  await page.getByLabel('Freight weight (kg)').fill('12.5');
  await page.getByLabel('Package count').fill('2');
  await page.getByLabel('Service level').selectOption('express');
  await page.getByRole('button', { name: 'GET FREIGHT QUOTE' }).click();

  await expect(page.getByText('DRY_RUN', { exact: true })).toBeVisible();
  await expect(page.getByText(/shipping charge was not added to the customer quote/i)).toBeVisible();
  await expect.poll(() => freightRequest).toEqual({ origin: 'MIA', destination: 'JFK', weight_kg: 12.5, packages: 2, service_level: 'express' });
});

test('admin can inspect the sales mailbox and send after confirmation', async ({ page }) => {
  let sentMessage: Record<string, unknown> | undefined;
  await seedSession(page, 'internal');
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/inventory', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/suppliers', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/mailboxes/sales/inbox', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ mailbox: 'sales', messages: [{
      mailbox: 'sales', message_id: 'MSG-SALES-1', from: 'buyer@example.com',
      subject: 'PN-100 availability', date: '2026-09-28T10:00:00Z', body: 'Please confirm current availability.',
    }] }),
  }));
  await page.route('**/api/internal/mailboxes/sales/send', async route => {
    sentMessage = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'sent', mailbox: 'sales', sent_by: 'camila@wingedtycoons.com' }) });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await expect(page.getByRole('heading', { name: 'MAILBOX OPERATIONS' })).toBeVisible();
  await expect(page.getByText('Please confirm current availability.')).toBeVisible();
  await page.getByLabel('Mailbox recipient').fill('buyer@example.com');
  await page.getByLabel('Mailbox subject').fill('PN-100 availability');
  await page.getByLabel('Mailbox message').fill('PN-100 is available; a quote will follow.');
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'SEND MESSAGE' }).click();

  await expect(page.getByText(/Message sent from the sales mailbox/)).toBeVisible();
  await expect.poll(() => sentMessage).toEqual({ recipient: 'buyer@example.com', subject: 'PN-100 availability', body: 'PN-100 is available; a quote will follow.' });
});

test('purchasing users only load the purchasing mailbox', async ({ page }) => {
  let salesMailboxRequests = 0;
  let purchasingMailboxRequests = 0;
  await page.addInitScript(() => {
    localStorage.setItem('wt_access_token', 'e2e-purchasing-token');
    localStorage.setItem('wt_role', 'ROLE_PURCHASING');
    localStorage.setItem('wt_email', 'purchasing@example.com');
  });
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/supplier-offers**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/mailboxes/sales/inbox', route => {
    salesMailboxRequests += 1;
    return route.fulfill({ status: 403, contentType: 'application/json', body: '{}' });
  });
  await page.route('**/api/internal/mailboxes/purchasing/inbox', route => {
    purchasingMailboxRequests += 1;
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ mailbox: 'purchasing', messages: [] }) });
  });

  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();
  await expect(page.getByRole('heading', { name: 'MAILBOX OPERATIONS' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Purchasing mailbox' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Sales mailbox' })).toHaveCount(0);
  await expect.poll(() => purchasingMailboxRequests).toBeGreaterThan(0);
  expect(salesMailboxRequests).toBe(0);
});
