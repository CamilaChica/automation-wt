import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const authStatePath = resolve(process.cwd(), 'playwright/.auth/user.json');

test('Authenticated user can access internal mailbox status', async ({ page }) => {
  let mailboxAuthorization: string | undefined;
  let rejectMailbox = false;

  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path.endsWith('/auth/otp/request')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ challenge_id: 'playwright-challenge' }),
      });
      return;
    }
    if (path.endsWith('/auth/otp/verify')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Set-Cookie': 'wt_session=playwright-session; HttpOnly; Path=/; SameSite=Strict' },
        body: JSON.stringify({
          access_token: 'playwright-test-token',
          token_type: 'bearer',
          role: 'ROLE_ADMIN',
          email: 'operator@wingedtycoons.com',
        }),
      });
      return;
    }
    if (path.endsWith('/internal/mailboxes/health')) {
      mailboxAuthorization = request.headers().authorization;
      if (rejectMailbox) {
        await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid session' }) });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sales_mailbox: 'ok',
          purchasing_mailbox: 'ok',
          authenticated_user: 'operator@wingedtycoons.com',
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  await page.goto('/internal');
  await page.getByLabel('Work email').fill('operator@wingedtycoons.com');
  await page.getByRole('button', { name: 'Send one-time code' }).click();
  await page.getByLabel('One-time code').fill('123456');
  await page.getByRole('button', { name: 'Verify code' }).click();

  const mailboxState = await page.evaluate(async () => {
    const { apiService } = await import('/src/services/api.ts');
    return apiService.getMailboxHealth();
  });
  expect(mailboxState.sales?.status).toBe('ok');
  expect(mailboxState.purchasing?.status).toBe('ok');
  expect(mailboxAuthorization).toBe('Bearer playwright-test-token');

  await mkdir(dirname(authStatePath), { recursive: true });
  await page.context().storageState({ path: authStatePath });

  rejectMailbox = true;
  await page.evaluate(async () => {
    const { apiService } = await import('/src/services/api.ts');
    await apiService.getMailboxHealth().catch(() => undefined);
  });
  await expect(page.getByLabel('Work email')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('wt_access_token'))).toBeNull();
});