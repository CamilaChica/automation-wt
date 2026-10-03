import { expect, test } from '@playwright/test';

const rfq = {
  id: 'RFQ-FEEDBACK-001',
  customer_name: 'Test MRO',
  customer_email: 'buyer@example.test',
  status: 'Intake',
  raw_text: 'Request one actuator.',
  created_at: '2026-10-03T14:00:00Z',
  part_number: 'ACT-100',
  quantity: 1,
};

const scenarios = [
  { name: 'queued dispatch', response: { status: 'Quote_Dispatch_Pending', transmission_status: 'QUEUED' }, role: 'status', text: 'Email dispatch is not confirmed.' },
  { name: 'confirmed dispatch', response: { status: 'Quote_Sent', quote_id: 'Q-TEST' }, role: 'status', text: 'Email dispatch confirmed; inbox receipt is not verified.' },
  { name: 'workflow failure', response: { status: 'Quote_Dispatch_Failed', error: 'Mailbox unavailable.' }, role: 'alert', text: 'Mailbox unavailable.' },
  { name: 'missing status', response: {}, role: 'alert', text: 'The API returned no workflow status.' },
] as const;

const views = [
  { name: 'operations', preference: 'customer', button: 'Process' },
  { name: 'procurement', preference: 'aero-procurement', button: 'PROCESS RFQ' },
];

for (const { view, scenario } of views.flatMap(view => scenarios.map(scenario => ({ view, scenario })))) {
  test(`RFQ Process feedback in ${view.name} shows ${scenario.name} without promising customer contact`, async ({ page }) => {
    let processCalls = 0;
    await page.addInitScript(preference => {
      localStorage.setItem('wt_role', 'ROLE_MANAGER');
      localStorage.setItem('wt_email', 'operator@example.test');
      document.cookie = `wt_internal_view=${preference}; Path=/`;
    }, view.preference);
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (!url.pathname.startsWith('/api/')) {
        if (url.hostname !== '127.0.0.1') return route.abort();
        return route.continue();
      }
      let body: unknown = [];
      if (url.pathname === `/api/rfqs/${rfq.id}/process`) {
        expect(route.request().method()).toBe('POST');
        processCalls += 1;
        body = scenario.response;
      } else if (url.pathname === '/api/rfqs') {
        body = [rfq];
      } else if (url.pathname === `/api/rfqs/${rfq.id}`) {
        body = { rfq, items: [], logs: [] };
      } else if (url.pathname === '/api/auth/csrf') {
        body = { csrf_token: 'mock-csrf-token' };
      } else if (url.pathname.includes('/mailboxes/')) {
        body = { mailbox: 'sales', messages: [] };
      } else if (url.pathname === '/api/internal/employee/profile') {
        body = { display_name: 'Test Operator', job_title: 'Manager', is_online: true };
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });
    await page.goto('/internal');
    await page.getByRole('button', { name: view.button, exact: true }).click();
    const notice = page.getByRole(scenario.role).filter({ hasText: rfq.id });
    await expect(notice).toContainText(scenario.text);
    await expect(page.getByText(/will be contacted automatically/)).toHaveCount(0);
    expect(processCalls).toBe(1);
  });
}
