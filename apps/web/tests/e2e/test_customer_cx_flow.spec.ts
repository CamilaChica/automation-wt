import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

class RFQPage {
  constructor(private page: import("@playwright/test").Page) {}
  async open() { await this.page.goto("/rfq"); }
  form() { return this.page.locator("form.rfq-card"); }
}

class QuotePortalPage {
  constructor(public page: import("@playwright/test").Page) {}
  async open(id = "QTE-9921") { await this.page.goto(`/quotes/${id}`); }
  async uploadAndAccept() {
    await this.page.getByLabel("Purchase order PDF").setInputFiles({ name: "po-9921.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 PO") });
    await this.page.getByRole("button", { name: /Submit PO & continue/i }).click();
  }
}

test("submits a valid RFQ and shows confirmation", async ({ page }) => {
  const rfq = new RFQPage(page);
  await rfq.open();
  await rfq.form().locator("input[name=name]").fill("Maria Buyer");
  await rfq.form().locator("input[name=company]").fill("Global Airlines");
  await rfq.form().locator("input[name=email]").fill("buyer@example.com");
  await rfq.form().locator("input[name=aircraft]").fill("B737-800");
  await rfq.form().locator("input[name=partNumber]").fill("XYZ123");
  await rfq.form().locator("input[name=quantity]").fill("2");
  await rfq.form().locator("input[name=requiredDate]").fill("2026-10-15");
  await rfq.form().locator("input[name=destination]").fill("Miami, FL");
  await rfq.form().getByRole("button", { name: /Send RFQ/i }).click();
  await expect(page.getByRole("dialog")).toContainText("Request received");
});

test("shows inline validation for invalid email and missing part", async ({ page }) => {
  const rfq = new RFQPage(page);
  await rfq.open();
  await rfq.form().locator("input[name=email]").fill("invalid-email");
  await rfq.form().locator("input[name=quantity]").fill("0");
  await rfq.form().getByRole("button", { name: /Send RFQ/i }).click();
  await expect(page.locator(".error")).toContainText("valid work email");
});

test("views quote and transitions to PO_RECEIVED without reload", async ({ page }) => {
  const quote = new QuotePortalPage(page);
  await quote.open();
  await expect(page.getByText("XYZ123")).toBeVisible();
  await expect(page.getByText("$9,200.00")).toBeVisible();
  await quote.page.getByRole("button", { name: /Accept & Upload PO/i }).click();
  await quote.uploadAndAccept();
  await expect(page.locator(".status-pill")).toHaveText("PO_RECEIVED");
});

test.describe("WCAG 2.1 AA smoke checks", () => {
  for (const project of ["desktop", "mobile"]) {
    test(`has no serious accessibility violations on ${project}`, async ({ page }) => {
      if (project === "mobile") await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/rfq");
      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations.filter(item => ["critical", "serious"].includes(item.impact || ""))).toEqual([]);
    });
  }
});
