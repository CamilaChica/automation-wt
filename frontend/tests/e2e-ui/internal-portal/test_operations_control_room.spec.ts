import { expect, test } from '@playwright/test';
import { seedInternalSession } from '../fixtures/session';

test('shows authenticated operations activity and allows a manual client reply', async ({ page }) => {
  let sentMessage: unknown;
  let supplierCounteroffer: unknown;
  let extractionDecision: unknown;
  let poApproval: unknown;
  await page.route('**/api/rfqs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'RFQ-OPS-001',
      customer_name: 'Northstar Aviation',
      customer_email: 'maintenance@northstar.example',
      status: 'Pending_Approval',
      raw_text: 'Need one actuator assembly.',
      created_at: '2026-10-03T14:00:00Z',
      part_number: 'ACT-100',
      quantity: 1,
    }, {
      id: 'RFQ-OPS-PO-001',
      customer_name: 'Northstar Aviation',
      customer_email: 'maintenance@northstar.example',
      status: 'PENDING_PO_REVIEW',
      raw_text: 'Purchase order for one actuator assembly.',
      created_at: '2026-10-03T13:00:00Z',
      part_number: 'ACT-100',
      quantity: 1,
    }]),
  }));
  await page.route('**/api/rfqs/RFQ-OPS-001', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      rfq: {
        id: 'RFQ-OPS-001',
        customer_name: 'Northstar Aviation',
        customer_email: 'maintenance@northstar.example',
        status: 'Pending_Approval',
        raw_text: 'Need one actuator assembly.',
        created_at: '2026-10-03T14:00:00Z',
      },
      items: [],
      logs: [],
    }),
  }));
  await page.route('**/api/rfqs/RFQ-OPS-PO-001', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      rfq: {
        id: 'RFQ-OPS-PO-001',
        customer_name: 'Northstar Aviation',
        customer_email: 'maintenance@northstar.example',
        status: 'PENDING_PO_REVIEW',
        raw_text: 'Purchase order for one actuator assembly.',
        created_at: '2026-10-03T13:00:00Z',
        part_number: 'ACT-100',
        quantity: 1,
      },
      items: [],
      logs: [],
      quote_details: {
        quote: { id: 'QTE-OPS-PO-001', rfq_id: 'RFQ-OPS-PO-001', subtotal: 2400, shipping_cost: 0, total_amount: 2400, status: 'Approved' },
        items: [],
      },
    }),
  }));
  await page.route('**/api/auth/csrf', route => route.fulfill({
    status: 200,
    headers: { 'x-csrf-token': 'ui-csrf-token' },
    contentType: 'application/json',
    body: JSON.stringify({ csrf_token: 'ui-csrf-token' }),
  }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'AUT-OPS-001',
      event_type: 'client_email_parsed',
      entity_type: 'rfq',
      entity_id: 'RFQ-OPS-001',
      status: 'SUCCEEDED',
      attempts: 1,
      max_attempts: 3,
      result: 'RFQ created from client email',
      created_at: '2026-10-03T14:01:00Z',
    }]),
  }));
  await page.route('**/api/internal/extraction-reviews**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'REV-OPS-001',
      status: 'PENDING',
      task: 'client_rfq',
      entity_id: 'RFQ-OPS-001',
      source_text: 'Need one actuator assembly.',
      extraction: { part_number: 'ACT-100', quantity: 1 },
      reason: 'Part condition requires confirmation.',
      created_at: '2026-10-03T14:00:00Z',
    }]),
  }));
  await page.route('**/api/internal/extraction-reviews/REV-OPS-001/decision', async route => {
    extractionDecision = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'approved' }) });
  });
  await page.route('**/api/internal/mailboxes/sales/inbox', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      mailbox: 'sales',
      messages: [{
        mailbox: 'sales',
        message_id: 'MAIL-OPS-001',
        from: 'Northstar Maintenance <maintenance@northstar.example>',
        subject: 'RE: Actuator availability',
        date: '2026-10-03T14:02:00Z',
        body: 'Can you confirm the condition?',
      }],
    }),
  }));
  await page.route('**/api/internal/mailboxes/purchasing/inbox', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      mailbox: 'purchasing',
      messages: [{
        mailbox: 'purchasing',
        message_id: 'MAIL-SUPPLIER-001',
        from: 'Parts Source <quotes@partssource.example>',
        subject: 'Quote for actuator assembly',
        date: '2026-10-03T13:50:00Z',
        body: 'We can supply one unit at the quoted price.',
        attachments: [{ filename: 'quote.pdf', content_type: 'application/pdf' }],
      }],
    }),
  }));
  await page.route('**/api/internal/mailboxes/health', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      sales_mailbox: 'connected',
      purchasing_mailbox: 'connected',
      authenticated_user: 'camila@wingedtycoons.com',
    }),
  }));
  await page.route('**/api/internal/mailboxes/sales/send', async route => {
    sentMessage = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'sent', mailbox: 'sales', sent_by: 'camila@wingedtycoons.com' }),
    });
  });
  await page.route('**/api/internal/mailboxes/purchasing/send', async route => {
    supplierCounteroffer = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'sent', mailbox: 'purchasing', sent_by: 'camila@wingedtycoons.com' }),
    });
  });
  await page.route('**/api/purchase-orders/QTE-OPS-PO-001/approve', async route => {
    poApproval = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'approved', quote_id: 'QTE-OPS-PO-001', rfq_id: 'RFQ-OPS-PO-001' }),
    });
  });

  await seedInternalSession(page);
  await page.goto('/internal');
  await page.getByRole('button', { name: 'Today' }).click();

  await expect(page.getByRole('heading', { name: 'Live Email & Agent Activity' })).toBeVisible();
  const operationsPanel = page.locator('.ops-panel').first();
  await expect(operationsPanel).toHaveCSS('background-color', 'rgb(11, 21, 34)');
  await page.getByRole('button', { name: 'Switch to light mode' }).click();
  await expect(page.locator('html')).toHaveClass(/light/);
  await expect(page.locator('.ops-control-room')).toHaveCSS('color-scheme', 'light');
  await expect(operationsPanel).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  await expect(page.getByText('RE: Actuator availability')).toBeVisible();
  await expect(page.getByText('RFQ created from client email')).toBeVisible();
  await page.getByRole('button', { name: 'Take Over Thread' }).click();

  const dialog = page.getByRole('dialog', { name: 'Take Over Client Thread' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveCSS('background-color', 'rgb(255, 255, 255)');
  await dialog.getByLabel('Message').fill('The part is available in overhauled condition.');
  await dialog.getByRole('button', { name: 'Send Reply' }).click();

  await expect(page.getByRole('status')).toContainText('Client reply sent');
  expect(sentMessage).toMatchObject({
    recipient: 'maintenance@northstar.example',
    subject: 'Re: Actuator availability',
    body: 'The part is available in overhauled condition.',
    reply_to: 'MAIL-OPS-001',
  });

  await page.getByRole('button', { name: 'Counteroffer' }).click();
  const supplierDialog = page.getByRole('dialog', { name: 'Supplier Negotiation' });
  await supplierDialog.getByLabel('Target Unit Cost (USD, Optional)').fill('1250');
  await supplierDialog.getByLabel('Message').fill('Please confirm this unit cost for the requested quantity.');
  await supplierDialog.getByRole('button', { name: 'Send Counteroffer' }).click();
  await expect(page.getByRole('status')).toContainText('Supplier counteroffer sent');
  expect(supplierCounteroffer).toMatchObject({
    recipient: 'quotes@partssource.example',
    reply_to: 'MAIL-SUPPLIER-001',
    body: 'Please confirm this unit cost for the requested quantity.\n\nTarget unit cost: $1,250.00',
  });

  await page.getByRole('button', { name: 'Review', exact: true }).click();
  const extractionDialog = page.getByRole('dialog', { name: 'Review Parsed Request' });
  await extractionDialog.getByLabel('Extracted Fields (JSON)').fill('{"part_number":"ACT-100","quantity":1,"condition":"OH"}');
  await extractionDialog.getByRole('button', { name: 'Approve Edited Fields' }).click();
  await expect(page.getByRole('status')).toContainText('Extraction reviewed and approved');
  expect(extractionDecision).toMatchObject({
    decision: 'approve',
    approved_extraction: { part_number: 'ACT-100', quantity: 1, condition: 'OH' },
  });

  await page.getByRole('button', { name: 'Review PO' }).click();
  const poDialog = page.getByRole('dialog', { name: 'Review Purchase Order' });
  await expect(poDialog.getByText('$2,400.00')).toBeVisible();
  await poDialog.getByLabel('Approval Notes').fill('PO total and part scope verified.');
  await poDialog.getByRole('button', { name: 'Approve PO' }).click();
  await expect(page.getByRole('status')).toContainText('PO approval recorded');
  expect(poApproval).toMatchObject({
    operator_name: 'camila@wingedtycoons.com',
    comments: 'PO total and part scope verified.',
  });
});

test('shows unavailable operations data instead of zero counts when APIs fail', async ({ page }) => {
  const unavailable = (route: import('@playwright/test').Route) => route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: 'Service unavailable' }),
  });
  await page.route('**/api/rfqs', unavailable);
  await page.route('**/api/internal/automation-events**', unavailable);
  await page.route('**/api/internal/extraction-reviews**', unavailable);
  await page.route('**/api/internal/mailboxes/**', unavailable);

  await seedInternalSession(page);
  await page.goto('/internal');
  await page.getByRole('button', { name: 'Today' }).click();

  await expect(page.getByRole('heading', { name: 'Operations Control Room' })).toBeVisible();
  await expect(page.locator('.ops-metric-value')).toHaveText(['—', '—', '—', '—']);
  await expect(page.getByText('DEGRADED')).toBeVisible();
  await expect(page.getByText('Activity unavailable. Check API connectivity and refresh.')).toBeVisible();
  await expect(page.getByText('Supplier inbox unavailable.')).toBeVisible();
  await expect(page.getByText('Review queue unavailable.')).toBeVisible();
  await expect(page.getByText('Purchase-order data unavailable.').first()).toBeVisible();
});
