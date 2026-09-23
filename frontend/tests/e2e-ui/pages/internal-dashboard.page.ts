import { expect, type Page } from '@playwright/test';

export class InternalDashboardPage {
  readonly page: Page;
  constructor(page: Page) { this.page = page; }

  async open() {
    await this.page.goto('/');
    await expect(this.page.getByAltText('Winged Tycoons Logo')).toBeVisible();
  }

  logo() {
    return this.page.getByRole('link', { name: 'Winged Tycoons Executive Dashboard' });
  }

  async openView(label: string | RegExp) {
    await this.page.getByRole('button', { name: label }).first().click();
  }

  async openAuditFeed() {
    await this.page.getByRole('button', { name: 'AGENT LOGS' }).click();
    await expect(this.page.getByText('MULTI-AGENT REASONING TIMELINE')).toBeVisible();
  }
}