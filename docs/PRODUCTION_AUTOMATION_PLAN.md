# Production Delivery Status

**Last updated:** 2026-10-02
**Target:** Deliver the customer portal today.
**Status:** Deployed and ready for customer onboarding.

## Live production services

- Customer portal: <https://winged-tycoons-customer-portal.onrender.com>
- API: <https://winged-tycoons-api.onrender.com>
- The existing internal static frontend remains unchanged.
- The dedicated customer portal is a live Render Node service. Its `API_BASE_URL` points to the HTTPS API, and `CUSTOMER_PORTAL_ORIGIN` is set to the portal's exact HTTPS origin.
- The API's live `OPERATIONAL_POSTGRES_RUNTIME_ENABLED` setting is `true`.
- API readiness returned HTTP 200 with `full_operational_persistence_ready: true`, `operational_store: postgresql`, migration head `0011_merge_postgres_migration_heads`, and no missing schema tables.

## Completed safe live checks

- API `/healthz`: HTTP 200.
- API readiness: HTTP 200; PostgreSQL operational persistence ready.
- Portal `/`: HTTP 200.
- Anonymous portal session lookup: HTTP 401, as expected.
- OTP proxy request with a valid origin and intentionally empty body: HTTP 422 from API validation, confirming proxy connectivity without requesting a code.
- OTP proxy request with a mismatched origin: HTTP 403, as expected.
- No OTP or other test email was sent.

## Customer onboarding

- Customer accounts are created on the customer's first eligible email OTP request; a bulk customer-user import is not required for customer sign-in.
- Share the portal URL with intended users. Their first real sign-in will send the OTP to their own email address.
- Internal staff accounts remain approval-controlled.
- Purchase-order submissions remain subject to human approval before fulfillment. The backend approval endpoint exists; a staff-facing pending-order queue was not verified as part of this deployment.

## Render service cleanup and configuration safety

- The live inventory has eight active services, including this portal, and four already-suspended services: `backend`, `frontend`, `winged-inventory-ingestion`, and `winged-tycoons-email-worker`.
- No active duplicate API or frontend service was found. The suspended services were left intact; no resource was deleted because the suspended `backend` and `frontend` entries may be needed for recovery, and the two worker entries are distinct services.
- Do not run Blueprint Sync as part of this delivery. `render.yaml` still contains stale worker definitions and declares the PostgreSQL runtime switch as `false`; a broad sync could recreate services or undo the live runtime setting. The live Render configuration is the current production state.

## Explicitly deferred by the owner

- Credential rotation will happen after delivery and successful end-user operation. It is not a release gate.
- SMS, analytics, maps, backup cleanup, and historical SQLite import are out of scope for this delivery.

## Delivery handoff

The portal and API are deployed and available for customer onboarding. Real-mail OTP delivery and business acceptance are to be confirmed through the intended user's normal onboarding, not through test emails. The deployment does not depend on credential rotation, a bulk customer-user import, or a broad Render Blueprint Sync.
