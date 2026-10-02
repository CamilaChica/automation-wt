import { expect, test } from '@playwright/test';
import { installAuditApiMocks } from './api-mocks';
import { signInWithMockOtp } from './auth-fixtures';
import { crawlPerspective } from './interactive-crawler';

test('client/public portal audit: anonymous and authenticated customer contexts', async ({ browser }, testInfo) => {
  const anonymousContext = await browser.newContext();
  const customerContext = await browser.newContext();
  try {
    await installAuditApiMocks(anonymousContext);
    await installAuditApiMocks(customerContext);

    const anonymousPage = await anonymousContext.newPage();
    const customerPage = await customerContext.newPage();
    await anonymousPage.goto('/', { waitUntil: 'domcontentloaded' });
    const anonymousReport = await crawlPerspective(
      anonymousContext,
      'public',
      ['/', '/customer-portal'],
      testInfo,
      { maxRoutes: 10, maxStates: 10, maxActions: 24, allowedRoutePrefixes: ['/', '/customer-portal', '/portal'] },
    );

    await customerPage.goto('/customer-portal', { waitUntil: 'domcontentloaded' });
    await signInWithMockOtp(customerPage, 'customer');
  const catalogInput = customerPage.getByRole('textbox', { name: 'Search aircraft parts' });
  const catalogSearch = customerPage.getByRole('button', { name: 'Search parts' });
  const trackingInput = customerPage.getByRole('textbox', { name: 'Tracking token' });
  const trackingSubmit = customerPage.getByRole('button', { name: 'Track a shipment' });
  await expect(catalogInput).toBeVisible();
  await expect(catalogSearch).toBeDisabled();
  await expect(trackingSubmit).toBeDisabled();
  await catalogInput.fill('32-11-45-01');
  await expect(catalogSearch).toBeEnabled();
  await catalogSearch.click();
  await expect(customerPage.getByText('32-11-45-01', { exact: true }).first()).toBeVisible();
  await trackingInput.fill('AUDIT-TRACK-1001');
  await expect(trackingSubmit).toBeEnabled();
  await trackingSubmit.click();
  await expect(customerPage.getByText('In Transit', { exact: true })).toBeVisible();

    const customerReport = await crawlPerspective(
      customerContext,
      'customer',
      ['/customer-portal'],
      testInfo,
      { maxRoutes: 10, maxStates: 12, maxActions: 28, allowedRoutePrefixes: ['/', '/customer-portal', '/portal'] },
    );

    expect(anonymousReport.counts.errors, JSON.stringify(anonymousReport.findings, null, 2)).toBe(0);
    expect(customerReport.counts.errors, JSON.stringify(customerReport.findings, null, 2)).toBe(0);
    expect(await anonymousPage.evaluate(() => localStorage.getItem('wt_role'))).toBeNull();
    expect(await customerPage.evaluate(() => localStorage.getItem('wt_role'))).toBe('ROLE_CUSTOMER');
    expect(anonymousReport.routes.length).toBeGreaterThan(0);
    expect(customerReport.interactions.length).toBeGreaterThan(0);
  } finally {
    await Promise.all([anonymousContext.close(), customerContext.close()]);
  }
});