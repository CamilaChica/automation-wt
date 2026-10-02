import { expect, test } from '@playwright/test';

test('internal team portal presents the mission and protected workspace access', async ({ page }) => {
  await page.goto('/team-portal');

  await expect(page).toHaveTitle('Winged Tycoons | Internal Team Portal');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Every flight has');
  await expect(page.getByRole('heading', { name: /a part number is never/i })).toBeVisible();
  await expect(page.getByRole('link', { name: /crew login/i })).toHaveAttribute('href', '/internal');
  await expect(page.getByRole('link', { name: /enter the team workspace/i })).toHaveAttribute('href', '/internal');
  await expect(page.getByRole('img', { name: /diverse group of teammates/i })).toBeVisible();
  await expect(page.locator('.wt-team-operations').getByRole('img', { name: /operations professional reviews a clipboard/i })).toBeVisible();
  await expect(page.locator('.wt-team-sales').getByRole('img', { name: /three colleagues work together reviewing documents/i })).toBeVisible();
  await expect(page.locator('.wt-team-portal')).toHaveCSS('font-family', /Montserrat/);
  await expect(page.locator('.wt-team-portal')).toHaveCSS('background-color', 'rgb(243, 247, 252)');

  await page.route('**/api/rfqs*', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('link', { name: /enter the team workspace/i }).click();
  await expect(page).toHaveURL(/\/internal$/);
  await expect(page.getByRole('heading', { name: 'Secure sign in' })).toBeVisible();
});

test('internal team portal navigation works on mobile without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto('/team-portal');

  const menuButton = page.getByRole('button', { name: 'Open navigation menu' });
  await expect(menuButton).toBeVisible();
  await menuButton.click();
  const navigation = page.getByRole('navigation', { name: 'Team portal navigation' });
  await expect(navigation).toBeVisible();
  await navigation.getByRole('link', { name: 'Sales' }).click();
  await expect(page).toHaveURL(/#sales$/);

  for (const width of [320, 375, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
  }
});
