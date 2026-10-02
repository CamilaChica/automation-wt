import { expect, test } from '@playwright/test';

test('acquisition landing page exposes the sourcing story and key actions', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveTitle(/Winged Tycoons.*Autonomous AOG/i);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Keep aircraft moving.');
  await expect(page.locator('.wt-header .wt-brand img')).toHaveAttribute('src', '/branding/WingedTycoons.png');
  await expect(page.getByRole('link', { name: /login/i })).toHaveAttribute('href', '/customer-portal');
  await expect(page.getByRole('link', { name: /see it on a real RFQ/i })).toHaveAttribute('href', /mailto:sales@wingedtycoons\.com/);
  await expect(page.getByRole('heading', { name: /Autonomous.*Accountable by default/i })).toBeVisible();
  await expect(page.locator('.wt-hero-photo')).toHaveCSS('background-image', /winged-aircraft-engine\.jpg/);
});

test('mobile landing page navigation and primary actions stay usable without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto('/');

  const menuButton = page.getByRole('button', { name: 'Open navigation menu' });
  await expect(menuButton).toBeVisible();
  await menuButton.click();
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'How it works' }).click();
  await expect(page).toHaveURL(/#workflow$/);

  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  await expect(page.getByRole('link', { name: /request a live demonstration/i })).toBeVisible();
});
