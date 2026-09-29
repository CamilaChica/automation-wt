import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test('admin interface audits logs and triggers hard freeze', async ({ page }) => {
  await seedSession(page, 'internal');
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([{ id: 'WT-ADMIN-1', customer_name: 'Admin Test', customer_email: 'admin@example.com', status: 'Quoted', raw_text: 'test', created_at: new Date().toISOString() }]) }));
  await page.route('**/api/internal/rfqs/*/trace-decision', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ decision: 'freeze', automation_paused: true }) }));
  await page.goto('/');

  await page.getByRole('button', { name: 'Open notifications and agent activity' }).click();
  await expect(page.getByRole('heading', { name: 'AGENT ACTIVITY LOG' })).toBeVisible();
  await expect(page.getByText(/Milo · RFQ Intake/)).toBeVisible();
  await page.getByRole('button', { name: 'Close audit log' }).click();

  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();
  await expect(page.getByText('DOCUMENT REVIEW & VERIFICATION TERMINAL')).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'HARD FREEZE ORDER' }).click();

  await expect(page.getByText(/Trace decision freeze recorded|Order hard freeze active/).first()).toBeVisible();
  await expect(page.getByText('Verification state: REVIEW_REQUIRED')).toBeVisible();
});

test('admin can pause and resume RFQ automation with an audit reason', async ({ page }) => {
  let automationPaused = false;
  let pauseReason: string | null = null;
  const automationRequests: Array<{ paused: boolean; reason?: string }> = [];

  await page.route('**/api/rfqs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'WT-PAUSE-1',
      customer_name: 'Pause Test',
      customer_email: 'pause@example.com',
      status: 'Intake',
      raw_text: 'Test automation controls',
      part_number: 'PN-PAUSE-1',
      automation_paused: automationPaused,
      pause_reason: pauseReason,
      created_at: new Date().toISOString(),
    }]),
  }));
  await page.route('**/api/supplier-offers**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/internal/rfqs/WT-PAUSE-1/automation', async route => {
    const request = route.request().postDataJSON() as { paused: boolean; reason?: string };
    automationRequests.push(request);
    automationPaused = request.paused;
    pauseReason = request.paused ? request.reason || null : null;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ rfq_id: 'WT-PAUSE-1', automation_paused: automationPaused, pause_reason: pauseReason }),
    });
  });
  await seedSession(page, 'internal');
  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Proc Command' }).first().click();

  await page.getByLabel('Reason for pausing automation').fill('Waiting for export-control review.');
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'PAUSE AUTOMATION' }).click();
  await expect(page.getByRole('button', { name: 'RESUME AUTOMATION' })).toBeVisible();
  await expect.poll(() => automationRequests[0]).toEqual({ paused: true, reason: 'Waiting for export-control review.' });

  await page.getByRole('button', { name: 'RESUME AUTOMATION' }).click();
  await expect(page.getByRole('button', { name: 'PAUSE AUTOMATION' })).toBeVisible();
  await expect.poll(() => automationRequests[1]).toEqual({ paused: false });
});

test('admin can review and approve a source-grounded extraction', async ({ page }) => {
  const extraction = {
    customer_name: 'Global Airlines',
    customer_email: 'buyer@global.example',
    items: [{ requested_part_number: 'PN-100', quantity: 1, condition_preference: 'NE' }],
  };
  let reviewStatus = 'PENDING';
  let decisionPayload: Record<string, unknown> | undefined;

  await page.route('**/api/rfqs', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([]),
  }));
  await page.route('**/api/internal/extraction-reviews/REV-ADMIN-1', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      id: 'REV-ADMIN-1',
      task: 'rfq_extraction',
      entity_id: 'WT-REVIEW-1',
      source_text: 'Please quote PN-100, quantity 1, for Global Airlines.',
      extraction,
      reason: 'Low extraction confidence requires operator approval.',
      hold_flags: ['LOW_CONFIDENCE'],
      status: reviewStatus,
      created_at: new Date().toISOString(),
    }),
  }));
  await page.route(url => url.pathname === '/api/internal/extraction-reviews', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(reviewStatus === 'PENDING' ? [{
      id: 'REV-ADMIN-1',
      task: 'rfq_extraction',
      entity_id: 'WT-REVIEW-1',
      source_text: 'Please quote PN-100, quantity 1, for Global Airlines.',
      extraction,
      reason: 'Low extraction confidence requires operator approval.',
      hold_flags: ['LOW_CONFIDENCE'],
      status: reviewStatus,
      created_at: new Date().toISOString(),
    }] : []),
  }));
  await page.route('**/api/internal/extraction-reviews/REV-ADMIN-1/decision', async route => {
    decisionPayload = route.request().postDataJSON();
    reviewStatus = 'APPROVED';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ review_id: 'REV-ADMIN-1', status: reviewStatus, decision_by: 'camila@wingedtycoons.com' }),
    });
  });
  await seedSession(page, 'internal');
  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();

  await expect(page.getByRole('heading', { name: 'OPERATOR EXTRACTION REVIEWS' })).toBeVisible();
  await page.getByRole('button', { name: /REV-ADMIN-1/ }).click();
  await expect(page.getByText('Please quote PN-100, quantity 1, for Global Airlines.')).toBeVisible();
  await expect(page.getByText('LOW_CONFIDENCE')).toBeVisible();
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'APPROVE EXTRACTION' }).click();

  await expect(page.getByText(/Extraction review approved/)).toBeVisible();
  await expect.poll(() => decisionPayload).toMatchObject({ decision: 'approve', approved_extraction: extraction });
});

test('admin must provide a reason before rejecting an extraction review', async ({ page }) => {
  let decisionPayload: Record<string, unknown> | undefined;
  const review = {
    id: 'REV-REJECT-1',
    task: 'rfq_extraction',
    entity_id: 'WT-REVIEW-2',
    source_text: 'Please quote PN-200, quantity 2.',
    extraction: { items: [{ requested_part_number: 'PN-200', quantity: 2 }] },
    reason: 'Part number could not be verified.',
    hold_flags: ['UNVERIFIED_PART_NUMBER'],
    status: 'PENDING',
  };

  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/extraction-reviews/REV-REJECT-1', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(review) }));
  await page.route(url => url.pathname === '/api/internal/extraction-reviews', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([review]),
  }));
  await page.route('**/api/internal/extraction-reviews/REV-REJECT-1/decision', async route => {
    decisionPayload = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ review_id: review.id, status: 'REJECTED' }) });
  });
  await seedSession(page, 'internal');
  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();
  await expect(page.getByText(review.source_text)).toBeVisible();

  const rejectButton = page.getByRole('button', { name: 'REJECT EXTRACTION' });
  await expect(rejectButton).toBeDisabled();
  await page.getByLabel('Extraction review comments').fill('Part identity does not match the source email.');
  page.on('dialog', dialog => dialog.accept());
  await rejectButton.click();

  await expect(page.getByText(/Extraction review rejected/)).toBeVisible();
  await expect.poll(() => decisionPayload).toMatchObject({
    decision: 'reject',
    comments: 'Part identity does not match the source email.',
  });
});

test('admin can inspect LLM health and telemetry without exposing credentials', async ({ page }) => {
  await page.route('**/api/rfqs', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/automation-events**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/extraction-reviews**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }));
  await page.route('**/api/internal/llm/health', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      default_provider: 'openai',
      customer_communication_provider: 'openai',
      openai_configured: true,
      anthropic_configured: false,
      gemini_configured: false,
      fallback_enabled: true,
      api_key: 'DO_NOT_RENDER_SECRET',
    }),
  }));
  await page.route('**/api/internal/llm/telemetry**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify([{
      id: 'LLM-ADMIN-1',
      task: 'rfq_extraction',
      prompt_version: 'v3',
      model_id: 'gpt-test',
      model_calls: ['gpt-test'],
      latency_ms: 125,
      input_tokens: 40,
      output_tokens: 12,
      estimated_cost_usd: 0.004,
      validation_result: 'PASS',
      operator_review_outcome: null,
      review_queue_id: null,
      created_at: '2026-09-28T12:00:00Z',
    }]),
  }));
  await seedSession(page, 'internal');
  await page.goto('/');
  await page.locator('aside button').filter({ hasText: 'Trace Vault' }).first().click();

  await expect(page.getByRole('heading', { name: 'LLM PROVIDER HEALTH & TELEMETRY' })).toBeVisible();
  await expect(page.getByText('openai', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('rfq_extraction', { exact: true }).last()).toBeVisible();
  await expect(page.getByText('DO_NOT_RENDER_SECRET')).toHaveCount(0);
});
