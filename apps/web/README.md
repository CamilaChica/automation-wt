# Customer RFQ portal

The portal uses the existing customer email one-time-code flow. It submits RFQs,
loads only sent quotes owned by the signed-in customer, and collects the three
PDFs required for purchase-order review.

## Run locally

1. Start the API using its normal development configuration.
2. Set `API_BASE_URL` for the Next.js server to the API origin (for example,
   `http://127.0.0.1:8000`). This is server-only; do not expose it with a
   `NEXT_PUBLIC_` prefix.
3. Set `CUSTOMER_PORTAL_ORIGIN` to the portal's origin (for example,
   `http://127.0.0.1:3000` locally and the public HTTPS origin in production).
4. Run `npm run dev` from `apps/web`.

Production sends the OTP to the customer's email. For local development, the
API's development-only OTP is intentionally stripped by the portal proxy; get
the code from the local API response in a terminal and enter it in the portal:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/otp/request `
  -ContentType "application/json" `
  -Body '{"email":"buyer@example.com","role":"CUSTOMER"}'
```

The portal never returns an OTP or session token to browser code.

## Checks

From the repository root:

```powershell
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e -- --project=chromium
```

The browser tests mock the API responses and do not replace a staging or
PostgreSQL integration test.
