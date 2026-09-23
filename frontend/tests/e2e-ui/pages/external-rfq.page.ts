import { expect, type Page } from '@playwright/test';

export class ExternalRFQPage {
  readonly page: Page;
  constructor(page: Page) { this.page = page; }

  async open() {
    await this.page.goto('/customer-portal');
    await expect(this.page.getByText('Customer parts portal')).toBeVisible();
  }

  quoteForm() {
    return this.page.getByRole('form', { name: 'Request a quote form' });
  }

  purchaseOrderForm() {
    return this.page.getByRole('form', { name: 'Purchase order form' });
  }

  async submitRfq() {
    const form = this.quoteForm();
    await form.getByPlaceholder('e.g., Global Airlines').fill('Global Airlines');
    await form.getByPlaceholder('e.g., buyer@airline.com').fill('buyer@example.com');
    await form.getByPlaceholder('e.g., BACB30LU-4').fill('XYZ123');
    await form.getByLabel('Quantity').fill('2');
    await form.getByPlaceholder(/Condition, aircraft type/).fill('B737, OH, FAA 8130-3, Miami');
    await form.getByLabel(/I confirm this order/).check();
    await form.getByRole('button', { name: 'Send request' }).click();
  }
}