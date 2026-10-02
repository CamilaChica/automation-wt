import { expect, type Page } from '@playwright/test';
import type { AuditPersona } from './audit-types';

export async function signInWithMockOtp(page: Page, persona: 'customer' | 'internal'): Promise<void> {
  const email = persona === 'customer' ? 'customer@example.test' : 'operator@wingedtycoons.com';
  await expect(page.getByLabel('Work email')).toBeVisible();
  await page.getByLabel('Work email').fill(email);
  await page.getByRole('button', { name: 'Send one-time code' }).click();
  await expect(page.getByLabel('One-time code')).toBeVisible();
  await page.getByLabel('One-time code').fill('123456');
  await page.getByRole('button', { name: 'Verify code' }).click();
  if (persona === 'customer') await expect(page.getByText(/Customer portal/i).first()).toBeVisible();
  else await expect(page.getByRole('main')).toBeVisible();
}

export async function seedLocalRole(page: Page, persona: Exclude<AuditPersona, 'public'>): Promise<void> {
  const role = persona === 'customer' ? 'ROLE_CUSTOMER' : 'ROLE_ADMIN';
  const email = persona === 'customer' ? 'customer@example.test' : 'operator@wingedtycoons.com';
  await page.addInitScript(({ sessionRole, sessionEmail }) => {
    localStorage.setItem('wt_role', sessionRole);
    localStorage.setItem('wt_email', sessionEmail);
    localStorage.removeItem('wt_access_token');
  }, { sessionRole: role, sessionEmail: email });
}