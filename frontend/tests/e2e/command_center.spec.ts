import { expect, test } from '@playwright/test';
import { seedSession } from './helpers/session';

test.describe('internal command center shell', () => {
  test('renders linked branded logo and opens the audit feed', async ({ page }) => {
    await seedSession(page, 'internal');
    await page.goto('/');

    const logo = page.getByAltText('Winged Tycoons Logo');
    await expect(logo).toBeVisible();
    await expect(page.getByRole('link', { name: 'Winged Tycoons Executive Dashboard' })).toHaveAttribute('href', '/');

    await page.getByRole('button', { name: 'Open notifications and agent activity' }).click();
    await expect(page.getByRole('heading', { name: 'AGENT ACTIVITY LOG' })).toBeVisible();
  });

  test('keeps navigation usable at tablet width', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 });
    await seedSession(page, 'internal');
    await page.goto('/');

    await expect(page.getByAltText('Winged Tycoons Logo')).toBeVisible();
    await page.getByRole('button', { name: 'Open navigation menu' }).click();
    await page.getByRole('button', { name: /Sales Command/ }).click();
    await expect(page.getByText('GLOBAL RFQ INBOX')).toBeVisible();
  });
});
