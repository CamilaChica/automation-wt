import { expect, test } from '@playwright/test';
import { installAuditApiMocks } from './api-mocks';
import { signInWithMockOtp } from './auth-fixtures';
import { crawlPerspective } from './interactive-crawler';

test('internal/admin audit: sign-in gate and privileged workspace', async ({ browser }, testInfo) => {
  const guestContext = await browser.newContext();
  const adminContext = await browser.newContext();
  try {
    await installAuditApiMocks(guestContext);
    await installAuditApiMocks(adminContext);

    const guestReport = await crawlPerspective(
      guestContext,
      'public',
      ['/internal'],
      testInfo,
      { maxRoutes: 5, maxStates: 5, maxActions: 10, allowedRoutePrefixes: ['/internal'] },
    );
    const adminPage = await adminContext.newPage();
    await adminPage.goto('/internal', { waitUntil: 'domcontentloaded' });
    await signInWithMockOtp(adminPage, 'internal');
    expect(await adminPage.evaluate(() => localStorage.getItem('wt_role'))).toBe('ROLE_ADMIN');
    const adminReport = await crawlPerspective(
      adminContext,
      'internal',
      ['/internal'],
      testInfo,
      { maxRoutes: 3, maxStates: 6, maxActions: 8, allowedRoutePrefixes: ['/internal'] },
    );

    expect(guestReport.counts.errors, JSON.stringify(guestReport.findings, null, 2)).toBe(0);
    expect(adminReport.counts.errors, JSON.stringify(adminReport.findings, null, 2)).toBe(0);
    expect(adminReport.routes.length).toBeGreaterThan(0);
    expect(adminReport.interactions.length).toBeGreaterThan(0);
  } finally {
    await Promise.all([guestContext.close(), adminContext.close()]);
  }
});