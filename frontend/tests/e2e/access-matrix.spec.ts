import { expect, test } from '@playwright/test';

const authenticateAs = async (page: import('@playwright/test').Page, role: string) => {
  await page.addInitScript(({ activeRole }) => {
    localStorage.setItem('wt_access_token', 'e2e-token');
    localStorage.setItem('wt_email', 'e2e@wingedtycoons.com');
    localStorage.setItem('wt_role', activeRole);
  }, { activeRole: role });
};

test('sales role hides procurement-only views and keeps sales actions', async ({ page }) => {
  await authenticateAs(page, 'ROLE_SALES');
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Sales Command' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sourcing Matrix' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Proc Command' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sales Command' }).click();
  await expect(page.getByText('SMART QUOTE EDITOR')).toBeVisible();
});

test('purchasing role cannot issue quotes from sales view actions', async ({ page }) => {
  await authenticateAs(page, 'ROLE_PURCHASING');
  await page.goto('/');

  await expect(page.getByRole('button', { name: 'Sourcing Matrix' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Sales Command' })).toHaveCount(0);
});

test('customer role only accesses customer portal route', async ({ page }) => {
  await authenticateAs(page, 'ROLE_CUSTOMER');
  await page.goto('/customer-portal');

  await expect(page.getByText('Customer parts portal')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Find aircraft parts faster.' })).toBeVisible();
});
