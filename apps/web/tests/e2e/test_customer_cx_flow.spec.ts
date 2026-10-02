import { expect, Page, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const quoteFixture = {
  quote: {
    id: "QTE-9921",
    rfq_id: "RFQ-1001",
    subtotal: 9200,
    shipping_cost: 125,
    total_amount: 9325,
    status: "Sent",
    lead_time_days: 5,
    valid_until: "2027-10-15",
  },
  rfq_status: "Quote_Sent",
  items: [{
    part_number: "XYZ123",
    quantity: 2,
    unit_price: 4600,
    certificate_type: "FAA Form 8130-3",
    compliance_status: "Pass",
    condition: "Overhauled",
  }],
};

async function mockCustomerApi(page: Page, quoteStatus = "Sent") {
  let signedIn = false;
  let nextAttachment = 1;
  let submittedRFQ: Record<string, unknown> | null = null;
  let submittedPO: Record<string, unknown> | null = null;

  await page.route("**/api/customer/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/customer/", "");
    const method = request.method();

    if (method === "GET" && path === "auth/session") {
      if (!signedIn) return route.fulfill({ status: 401, json: { detail: "Sign in to continue." } });
      return route.fulfill({ status: 200, json: { email: "buyer@example.com", role: "ROLE_CUSTOMER" } });
    }
    if (method === "POST" && path === "auth/otp/request") {
      return route.fulfill({ status: 200, json: { challenge_id: "challenge-e2e", message: "Code sent." } });
    }
    if (method === "POST" && path === "auth/otp/verify") {
      signedIn = true;
      return route.fulfill({
        status: 200,
        headers: { "Set-Cookie": "wt_customer_session=e2e-session; HttpOnly; SameSite=Strict; Path=/" },
        json: { email: "buyer@example.com", role: "ROLE_CUSTOMER" },
      });
    }
    if (method === "POST" && path === "auth/logout") {
      signedIn = false;
      return route.fulfill({ status: 204, body: "" });
    }
    if (method === "POST" && path === "attachments") {
      return route.fulfill({
        status: 200,
        json: { attachment_id: `ATT-E2E-${nextAttachment++}`, status: "ACCEPTED" },
      });
    }
    if (method === "POST" && path === "rfqs/intake") {
      submittedRFQ = request.postDataJSON();
      return route.fulfill({
        status: 201,
        json: { rfq_id: "RFQ-E2E-1", status: "Intake", message: "Request received." },
      });
    }
    if (method === "GET" && path === "quotes/QTE-9921") {
      if (quoteStatus !== "Sent") {
        return route.fulfill({ status: 404, json: { detail: "Quote not found." } });
      }
      return route.fulfill({ status: 200, json: { ...quoteFixture, quote: { ...quoteFixture.quote, status: quoteStatus } } });
    }
    if (method === "POST" && path === "purchase-orders") {
      submittedPO = request.postDataJSON();
      return route.fulfill({
        status: 200,
        json: { status: "Pending_PO_Review", po_number: "PO-E2E-1", quote_id: quoteFixture.quote.id },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "Not found." } });
  });

  return {
    getSubmittedRFQ: () => submittedRFQ,
    getSubmittedPO: () => submittedPO,
  };
}

async function signIn(page: Page) {
  await page.getByLabel("Work email").fill("buyer@example.com");
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect(page.getByRole("status")).toContainText("one-time sign-in code");
  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await expect(page.getByText("Signed in as")).toContainText("buyer@example.com");
}

test("server proxy protects sessions and strips internal API fields", async ({ page }) => {
  await page.request.post("http://127.0.0.1:3210/__test/reset");
  let otpResponseBody: unknown;
  page.on("response", async response => {
    if (response.url().endsWith("/api/customer/auth/otp/request")) {
      otpResponseBody = await response.json();
    }
  });
  await page.goto("/rfq");
  await page.getByLabel("Work email").fill("buyer@example.com");
  await page.getByRole("button", { name: "Email me a code" }).click();
  await expect.poll(() => otpResponseBody).toBeDefined();
  expect(otpResponseBody).toMatchObject({ challenge_id: "challenge-e2e" });
  expect(otpResponseBody).not.toHaveProperty("development_otp");
  await page.getByLabel("One-time code").fill("123456");
  await page.getByRole("button", { name: "Verify and continue" }).click();
  await expect(page.getByText("Signed in as")).toContainText("buyer@example.com");
  expect(await page.context().cookies("http://127.0.0.1:3200")).toEqual(expect.arrayContaining([
    expect.objectContaining({ name: "wt_customer_session", httpOnly: true, sameSite: "Strict" }),
  ]));

  const deniedWrite = await page.request.post("http://127.0.0.1:3200/api/customer/auth/logout", {
    headers: { Origin: "https://attacker.example" },
  });
  expect(deniedWrite.status()).toBe(403);

  const origin = "http://127.0.0.1:3200";
  const uploadResponse = await page.request.post(`${origin}/api/customer/attachments`, {
    headers: { Origin: origin },
    multipart: {
      file: { name: "signed.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 signed") },
    },
  });
  expect(uploadResponse.status()).toBe(200);
  const attachment = await uploadResponse.json();
  expect(attachment).toHaveProperty("attachment_id");
  expect(attachment).not.toHaveProperty("stored_path");
  expect(attachment).not.toHaveProperty("sha256");

  const quoteResponse = await page.request.get(`${origin}/api/customer/quotes/QTE-9921`);
  expect(quoteResponse.status()).toBe(200);
  const safeQuote = await quoteResponse.json();
  expect(safeQuote.items[0]).not.toHaveProperty("unit_cost");

  const poResponse = await page.request.post(`${origin}/api/customer/purchase-orders`, {
    headers: { Origin: origin },
    data: { quote_id: "QTE-9921", po_number: "PO-PROXY-1", attachment_ids: [attachment.attachment_id] },
  });
  expect(poResponse.status()).toBe(200);
  const safePO = await poResponse.json();
  expect(safePO).toHaveProperty("status", "Pending_PO_Review");
  expect(safePO).not.toHaveProperty("internal_notification");
});

test("signs in with email OTP and submits an RFQ to the service", async ({ page }) => {
  const api = await mockCustomerApi(page);
  await page.goto("/rfq");
  await signIn(page);

  const form = page.locator("form.rfq-card");
  await form.locator("input[name=name]").fill("Maria Buyer");
  await form.locator("input[name=company]").fill("Global Airlines");
  await form.locator("input[name=aircraft]").fill("B737-800");
  await form.locator("input[name=partNumber]").fill("XYZ123");
  await form.locator("input[name=quantity]").fill("2");
  await form.locator("input[name=requiredDate]").fill("2027-10-15");
  await form.locator("input[name=destination]").fill("Miami, FL");
  await form.locator("input[type=file]").setInputFiles({
    name: "trace.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4 trace"),
  });
  await form.getByRole("button", { name: /Send RFQ/i }).click();
  await expect(page.getByRole("dialog")).toContainText("RFQ-E2E-1");
  expect(api.getSubmittedRFQ()).toMatchObject({
    customer_email: "buyer@example.com",
    customer_name: "Global Airlines",
    attachment_ids: ["ATT-E2E-1"],
  });
  expect(api.getSubmittedRFQ()?.raw_text).toContain("Part number: XYZ123");
});

test("validates required RFQ fields before sending", async ({ page }) => {
  await mockCustomerApi(page);
  await page.goto("/rfq");
  await signIn(page);
  await page.locator("form.rfq-card").getByRole("button", { name: /Send RFQ/i }).click();
  await expect(page.locator("input[name=name]")).toBeFocused();

  await page.locator("input[name=name]").fill("Maria Buyer");
  await page.locator("input[name=company]").fill("Global Airlines");
  await page.locator("input[name=aircraft]").fill("B737-800");
  await page.locator("input[name=partNumber]").fill("XYZ123");
  await page.locator("input[name=quantity]").fill("0");
  await page.locator("input[name=requiredDate]").fill("2027-10-15");
  await page.locator("input[name=destination]").fill("Miami, FL");
  await page.locator("form.rfq-card").getByRole("button", { name: /Send RFQ/i }).click();
  await expect(page.locator("input[name=quantity]")).toBeFocused();
});

test("shows a sent quote and submits the three required PO documents", async ({ page }) => {
  const api = await mockCustomerApi(page);
  await page.goto("/quotes/QTE-9921");
  await signIn(page);
  await expect(page.getByText("XYZ123")).toBeVisible();
  await expect(page.getByText("$9,325.00")).toBeVisible();
  await page.getByRole("button", { name: /Accept & upload documents/i }).first().click();
  await page.getByLabel("Purchase order number").fill("PO-E2E-1");
  for (const label of ["Signed export certification", "Completed KYC form", "Purchase order"]) {
    await page.getByLabel(label, { exact: true }).setInputFiles({
      name: `${label.toLowerCase().replaceAll(" ", "-")}.pdf`,
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 signed document"),
    });
  }
  await page.getByRole("button", { name: /Submit purchase order/i }).click();
  await expect(page.getByRole("status")).toContainText("Pending PO Review");
  expect(api.getSubmittedPO()).toMatchObject({
    quote_id: "QTE-9921",
    po_number: "PO-E2E-1",
    attachment_ids: ["ATT-E2E-1", "ATT-E2E-2", "ATT-E2E-3"],
  });
});

test("does not allow a customer to accept an unsent quote", async ({ page }) => {
  await mockCustomerApi(page, "Draft");
  await page.goto("/quotes/QTE-9921");
  await signIn(page);
  await expect(page.locator(".quote-state .error")).toContainText("Quote not found");
  await expect(page.getByRole("button", { name: /Accept & upload documents/i })).toHaveCount(0);
});

test.describe("WCAG 2.1 AA smoke checks", () => {
  for (const viewport of [
    { name: "desktop", width: 1280, height: 800 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    test(`has no serious accessibility violations on ${viewport.name}`, async ({ page }) => {
      const originalViewport = page.viewportSize();
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await mockCustomerApi(page);
      await page.goto("/rfq");
      await signIn(page);
      const results = await new AxeBuilder({ page }).analyze();
      expect(results.violations.filter(item => ["critical", "serious"].includes(item.impact || ""))).toEqual([]);
      if (originalViewport) await page.setViewportSize(originalViewport);
    });
  }
});
