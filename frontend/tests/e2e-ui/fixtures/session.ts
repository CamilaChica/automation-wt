import type { Page } from '@playwright/test';

export async function seedInternalSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('wt_access_token', 'ui-token');
    localStorage.setItem('wt_role', 'ROLE_ADMIN');
    localStorage.setItem('wt_email', 'camila@wingedtycoons.com');
  });
}

export async function seedCustomerSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('wt_access_token', 'ui-customer-token');
    localStorage.setItem('wt_role', 'ROLE_CUSTOMER');
    localStorage.setItem('wt_email', 'buyer@example.com');
  });
}