import { expect, test } from '@playwright/test';
import { InternalDashboardPage } from '../pages/internal-dashboard.page';
import { seedInternalSession } from '../fixtures/session';

test.describe('internal branding and navigation', () => {
  test('renders the official logo and links to the executive dashboard', async ({ page }) => {
    await seedInternalSession(page);
    const dashboard = new InternalDashboardPage(page);
    await dashboard.open();

    await expect(page.getByAltText('Winged Tycoons Logo')).toBeVisible();
    await expect(dashboard.logo()).toHaveAttribute('href', '/');
    await dashboard.openView('Sales Command');
    await expect(page.getByText('GLOBAL RFQ INBOX')).toBeVisible();
  });

  test('keeps the header usable at tablet width', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 900 });
    await seedInternalSession(page);
    const dashboard = new InternalDashboardPage(page);
    await dashboard.open();
    await expect(page.getByAltText('Winged Tycoons Logo')).toBeVisible();
    await expect(page.getByRole('button', { name: 'AGENT LOGS' })).toBeVisible();
  });
});