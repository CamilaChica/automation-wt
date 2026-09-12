import type { Page } from '@playwright/test';

export const seedSession = async (
  page: Page,
  persona: 'customer' | 'internal'
) => {
  const role = persona === 'customer' ? 'ROLE_CUSTOMER' : 'ROLE_ADMIN';
  const email =
    persona === 'customer'
      ? 'procurement@delta-mro.com'
      : 'camila@wingedtycoons.com';

  await page.addInitScript(
    ({ seededRole, seededEmail }) => {
      localStorage.setItem('wt_access_token', 'e2e-token');
      localStorage.setItem('wt_role', seededRole);
      localStorage.setItem('wt_email', seededEmail);
    },
    { seededRole: role, seededEmail: email }
  );
};
