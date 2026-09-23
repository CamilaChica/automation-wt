import { expect, test } from '@playwright/test';

const DEPLOYED_INTERNAL_URL = 'https://winged-tycoons-frontend.onrender.com/internal';

const navigationLabels = [
  /Dashboard/i,
  /Sourcing Matrix/i,
  /Proc Command/i,
  /Trace Vault/i,
  /Fulfillment/i,
  /Sales Command/i,
  /Swarm Runner/i,
];

const safeButtonPattern = /^(close|cancel|back|reset|refresh|open|view|details|show|hide|search|filter|next|previous|menu|theme|light|dark|toggle|logout|exit command center|sourcing matrix|proc command|trace vault|fulfillment(?: \(fch\))?|sales command|swarm runner|dashboard)/i;
const destructivePattern = /submit|send|approve|reject|issue|dispatch|purchase order|hard freeze|freeze|delete|remove|logout|exit|certify|escalate|split po|quick-add|add to quote|generate smart quote|request re-scan|seriali[sz]ed tamper/i;

function describeTarget(element: { textContent(): Promise<string | null> }) {
  return element.textContent().then(text => (text || '').replace(/\s+/g, ' ').trim().slice(0, 120));
}

async function installErrorCapture(page: import('@playwright/test').Page) {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedResponses: string[] = [];

  page.on('pageerror', error => pageErrors.push(error.stack || error.message));
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('response', response => {
    const status = response.status();
    if (status === 404 || status >= 500) {
      failedResponses.push(`${status} ${response.request().method()} ${response.url()}`);
    }
  });

  return { pageErrors, consoleErrors, failedResponses };
}

async function clickSafeInteractiveControls(
  page: import('@playwright/test').Page,
  visited: Set<string>,
) {
  const controls = page.locator('button:visible, [role="button"]:visible, article:visible, [data-testid*="card"]:visible');
  const count = Math.min(await controls.count(), 80);

  for (let index = 0; index < count; index += 1) {
    const control = controls.nth(index);
    if (!(await control.isVisible().catch(() => false))) continue;

    const text = ((await control.textContent().catch(() => '')) || '').replace(/\s+/g, ' ').trim();
    const ariaLabel = await control.getAttribute('aria-label').catch(() => null);
    const label = `${ariaLabel || ''} ${text}`.trim();
    if (!label || destructivePattern.test(label) || !safeButtonPattern.test(label)) continue;

    const key = `${label}:${index}`;
    if (visited.has(key)) continue;
    visited.add(key);

    await control.scrollIntoViewIfNeeded().catch(() => undefined);
    await control.click({ timeout: 2_000 }).catch(() => undefined);
    await page.waitForTimeout(100);
  }
}

test.describe('deployed application automatic UI crawler', () => {
  test('crawls navigation, safe buttons, cards, and drawers without runtime or 404/500 errors', async ({ page }) => {
    test.setTimeout(120_000);
    const capture = await installErrorCapture(page);
    const visited = new Set<string>();

    await page.goto(DEPLOYED_INTERNAL_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page).toHaveURL(/winged-tycoons-frontend\.onrender\.com/);

    const authenticationWall = page.getByText(/sign in|verification code|one-time password|authenticate/i).first();
    if (await authenticationWall.isVisible().catch(() => false)) {
      test.info().annotations.push({
        type: 'blocked-by-authentication',
        description: 'The deployed internal route requires a real OTP/session; no credentials are embedded in this crawler.',
      });
    } else {
      for (const label of navigationLabels) {
        const navigation = page.getByRole('button', { name: label }).first();
        if (!(await navigation.isVisible().catch(() => false))) continue;
        await navigation.click().catch(() => undefined);
        await page.waitForTimeout(200);
        await clickSafeInteractiveControls(page, visited);
      }

      await clickSafeInteractiveControls(page, visited);

      const drawers = page.locator('[role="dialog"]:visible, [class*="drawer"]:visible, [data-testid*="drawer"]:visible');
      const drawerCount = await drawers.count();
      for (let index = 0; index < drawerCount; index += 1) {
        const drawer = drawers.nth(index);
        if (await drawer.isVisible().catch(() => false)) {
          await describeTarget(drawer);
          await drawer.getByRole('button', { name: /close|dismiss/i }).first().click().catch(() => undefined);
        }
      }
    }

    expect(capture.pageErrors, 'Unhandled page errors').toEqual([]);
    expect(capture.consoleErrors, 'Browser console errors').toEqual([]);
    expect(capture.failedResponses, 'Unexpected 404/500 responses').toEqual([]);
  });
});
