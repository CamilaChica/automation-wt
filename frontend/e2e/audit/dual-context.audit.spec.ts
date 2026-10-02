import { expect, test } from '@playwright/test';
import { installAuditApiMocks } from './api-mocks';
import { seedLocalRole } from './auth-fixtures';
import { crawlPerspective } from './interactive-crawler';

test('customer and admin crawls run concurrently with isolated browser sessions', async ({ browser }, testInfo) => {
  const customerContext = await browser.newContext();
  const adminContext = await browser.newContext();
  try {
    await installAuditApiMocks(customerContext);
    await installAuditApiMocks(adminContext);
    const customerPage = await customerContext.newPage();
    const adminPage = await adminContext.newPage();
    await seedLocalRole(customerPage, 'customer');
    await seedLocalRole(adminPage, 'internal');
    await Promise.all([
      customerPage.goto('/customer-portal', { waitUntil: 'domcontentloaded' }),
      adminPage.goto('/internal', { waitUntil: 'domcontentloaded' }),
    ]);
    const [customerRole, adminRole] = await Promise.all([
      customerPage.evaluate(() => localStorage.getItem('wt_role')),
      adminPage.evaluate(() => localStorage.getItem('wt_role')),
    ]);
    expect(customerRole).toBe('ROLE_CUSTOMER');
    expect(adminRole).toBe('ROLE_ADMIN');

    const [customerReport, adminReport] = await Promise.all([
      crawlPerspective(customerContext, 'customer', ['/customer-portal'], testInfo, {
        maxRoutes: 8, maxStates: 10, maxActions: 22, allowedRoutePrefixes: ['/', '/customer-portal', '/portal'],
      }),
      crawlPerspective(adminContext, 'internal', ['/internal'], testInfo, {
        maxRoutes: 8, maxStates: 10, maxActions: 22, allowedRoutePrefixes: ['/internal'],
      }),
    ]);

    expect(customerReport.counts.errors, JSON.stringify(customerReport.findings, null, 2)).toBe(0);
    expect(adminReport.counts.errors, JSON.stringify(adminReport.findings, null, 2)).toBe(0);
  } finally {
    await Promise.all([customerContext.close(), adminContext.close()]);
  }
});