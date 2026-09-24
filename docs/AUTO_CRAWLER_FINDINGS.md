# UI Crawler Remediation Changes

Target: `https://winged-tycoons-frontend.onrender.com/internal`

## Remaining P0 Changes

### RFQ workflow state

- Trace intake from API receipt through persistence and orchestration transitions.
- Preserve canonical status, part number, quantity, and customer fields across all API/view mappings.
- Add fixture tests for extracted, pending, and failed RFQs.
- Ensure failed RFQs expose retry/escalation guidance and no mutation controls.

### Responsive layout verification

- The strict visual audit now covers `375x667`, `393x852`, `412x915`, and `768x1024` across all six internal views.
- The audit checks sidebar collapse, main-content width, element overlap, table/grid/card containment, and 44px interactive dimensions; scroll width alone is not sufficient.
- Source remediation now applies `min-height: 44px` to both internal authentication actions; the deployed build still reports the prior `261x42px` secondary sign-in control until redeployment.
- Deploy the frontend changes.
- Re-run authenticated viewport checks against the deployed build.
- Confirm document width equals viewport width with no horizontal scrollbar in production.

### Mutation safety

Affected views: Sales, Trace Vault, Fulfillment, and Supplier Sourcing.

- Add confirmation/cancellation dialogs.
- Add mutation-specific pending state, `aria-busy`, success, failure, retry, rollback, and duplicate-submission protection.
- Test quote approval/dispatch, certification, rejection, freeze, PO, email, and supplier add-to-quote only in staging with disposable records.

## Remaining P1 Changes

### Crawler payload assertions

File: `frontend/e2e/auto_crawler.spec.ts`

- Added route matrix coverage for `/internal`, `/internal/sales`, `/internal/sourcing`, `/internal/trace`, `/internal/procurement`, and `/internal/fulfillment`.
- Added RFQ, detail, automation-event, and attachment payload shape checks.
- Added safe interactive control crawling, dialog closure, state exclusivity, overflow checks, and failure screenshots.
- Local deployed crawl: 6 route cases passed; authenticated control and payload assertions remain pending behind the OTP wall.
- Add slow-network, API-failure, and authenticated mobile viewport scenarios.

### Accessibility verification

- Local mobile audit verifies accessible navigation names, 44px touch targets, and browser runtime errors across all six internal views.
- Strict deployed audit must be rerun after redeployment to confirm the authentication touch-target fix.
- Verify keyboard navigation and focus restoration for all drawers.
- Verify `role="status"`, `aria-live`, `aria-busy`, dialog labels, and accessible names with axe/Playwright.
- Ensure every dynamic state has mutually exclusive loading, empty, error, and data rendering.

### Staging mutation coverage

Add a staging-only suite for:

- Quote approval and dispatch
- Purchase orders
- Compliance certify/reject
- Hard freeze
- Email sending
- Supplier add-to-quote

Use disposable records and assert cleanup, duplicate prevention, rollback, and user feedback.

## Release Gate

- [ ] RFQ state mapping and persistence verified end-to-end
- [x] Fallback data clearly labelled
- [ ] Strict visual layout audit passes on all mobile/tablet viewports
- [ ] Mobile/tablet overflow reverified after deployment
- [ ] Mutation confirmation and rollback tested in staging
- [ ] Accessibility semantics verified with keyboard and axe
- [x] Crawler validates payload semantics when authenticated
- [ ] Backend suite passes within the release timeout
- [x] Frontend unit tests and build pass
- [ ] Authenticated crawler passes after the remediation deployment
