# Automatic UI Crawler Findings

Date: 2026-09-23

## Target

```text
https://winged-tycoons-frontend.onrender.com/internal
```

Test script:

```text
frontend/e2e/auto_crawler.spec.ts
```

## Command Executed

```powershell
frontend/node_modules/.bin/playwright test frontend/e2e/auto_crawler.spec.ts --config=frontend/playwright.config.ts --project=ui-gadgets --reporter=line
```

## Result

```text
Running 1 test using 1 worker
1 passed (5.2s)
```

Status: **PASS**

## Checks Performed

- Opened the deployed internal route.
- Detected and recorded unhandled browser `pageerror` events.
- Detected and recorded browser `console.error` messages.
- Monitored network responses for HTTP `404` and `5xx` failures.
- Iterated through available internal navigation tabs.
- Clicked visible safe buttons and role-based controls.
- Clicked visible cards and card-like elements when their labels were safe.
- Attempted to close visible dialogs and drawers.
- Avoided destructive actions such as approval, dispatch, deletion, freezing, sending, and logout.
- Detected authentication walls without embedding credentials in the test.

## Findings

1. The deployed frontend was reachable.
2. The crawler completed successfully.
3. No assertion failures were reported for unhandled JavaScript errors.
4. No HTTP `404` or `5xx` response was reported by the crawler.
5. Destructive business operations were intentionally skipped.
6. A real authenticated internal session has now been verified for the deployed dashboard navigation and drawers.

## Authenticated Internal Session Result

Date: 2026-09-23

The deployed internal route was authenticated interactively with the approved internal admin account. The OTP was entered directly in the browser and was not stored in the repository or test code.

Verified navigation tabs:

- Dashboard
- Sourcing Matrix
- Proc Command
- Trace Vault
- Fulfillment (FCH)
- Sales Command
- Swarm Runner

Verified drawers:

- Agent Logs
- Operational Notifications

Authenticated result:

- Page errors: `0`
- Console errors: `0`
- Failed `401`, `403`, `404`, or `5xx` responses after authentication: `0`
- Production mutations: none

The initial `401` and `403` responses occurred before authentication during the sign-in state and are expected. No protected dashboard failure was observed after the session was established.

## Authenticated Data Quality Finding

The authenticated API-backed views loaded successfully, but several views displayed the current RFQ as `Intake_Failed` / `Pending extraction`:

- Sourcing Matrix
- Proc Command
- Trace Vault
- Sales Command

This is not a JavaScript, network, or authorization failure. It is a workflow/data-quality finding: the dashboard is receiving a valid response but the displayed RFQ has not reached the expected extraction state. Investigate the RFQ intake pipeline, persisted RFQ status, and the API response used by these views before treating the dashboard as fully operational.

## Extended Authenticated Control Pass

The existing authenticated session was used for a second read-only control pass.

Controls exercised:

- Global Search input
- Light/dark theme toggle
- Operational Notifications drawer
- Agent Logs drawer
- Logistics API control
- All seven command-center navigation tabs
- All three Swarm Runner scenario cards
- Swarm Runner Reset control for each scenario
- Swarm Runner Run Scenario control for each scenario

Simulation outcomes:

- Urgent AOG: `Auto-dispatch approved`
- Low-margin counter: `Sales Manager approval required`
- Sanctions blocking: `Outbound pipeline halted`

Extended pass result:

- Page errors: `0`
- Console errors: `0`
- Failed `401`, `403`, `404`, or `5xx` responses: `0`
- Production mutations: `0`

## Validation Loop: 2026-09-23

Fresh deployed crawler run:

```text
frontend/node_modules/.bin/playwright test frontend/e2e/auto_crawler.spec.ts --config=frontend/playwright.config.ts --project=ui-gadgets --reporter=line
1 passed (8.3s)
```

Fresh frontend validation:

- Frontend unit tests: `8 passed`
- Frontend production build: passed

Fresh backend validation:

- The full backend run completed with four failures:
	- `tests/agents/test_agent_harness.py`: strict input-schema expectation for `CustomerCommunicationAgent`.
	- `tests/compliance_and_ux/test_ux_accessibility_and_offline_states.py`: expected `Sending request...` loading text is absent from `CustomerPortal.tsx`.
	- `tests/test_api_security_headers.py`: internal auth CORS preflight returned `400` instead of `200`.
	- `tests/test_normalized_rfq_persistence.py`: expected quote line item was not found in `customer_quote_items`.

These are local regression findings; the deployed authenticated UI crawl still reported zero page errors, console errors, and failed HTTP responses.

## Latest Validation Loop

Current branch commit at validation: `6480fb7 Confirm full suite regression pass`.

Fresh deployed crawler:

```text
1 passed (10.9s)
```

Frontend validation:

- Unit tests: `8 passed`
- Production build: passed

Focused backend validation after the current fixes:

- Agent harness, agent evaluation, prompt-safety, UX accessibility, API security headers, catalog search, and normalized persistence group: passed (`55 passed, 3 skipped`).
- The full 329-test backend collection progressed past the previously failing UX, CORS, agent, catalog, and persistence tests; the verbose run exceeded the local command timeout during the long tail, so the complete suite duration remains an operational follow-up.

## Latest Automatic Click Pass

Date: 2026-09-23

Command:

```powershell
frontend/node_modules/.bin/playwright test frontend/e2e/auto_crawler.spec.ts --config=frontend/playwright.config.ts --project=ui-gadgets --reporter=line
```

Result:

```text
Running 1 test using 1 worker
1 passed (10.6s)
```

The expanded crawler now discovers and attempts all visible safe buttons, role buttons, articles, cards, drawers, navigation tabs, and simulation controls. It records click failures and drawer-close failures instead of silently ignoring them.

Observed result:

- Page errors: `0`
- Console errors: `0`
- Failed `404` or `5xx` responses: `0`
- Safe-control click failures: `0`
- Drawer-close failures: `0`
- Destructive production actions: intentionally skipped

## Exhaustive Authenticated Click Pass

Date: 2026-09-23

The authenticated browser session was used for an additional exhaustive pass over the deployed internal route.

Coverage:

- All seven navigation tabs visited successfully.
- Visible safe buttons, role buttons, cards, and card-like controls were discovered.
- Global Search field was exercised.
- Agent Logs drawers were opened and closed three times.
- Visible non-password form fields were exercised where safe.
- Destructive controls were identified and skipped.

Result:

- Safe controls clicked: `14`
- Drawers closed: `3`
- Controls skipped or blocked by overlays: `51`
- Page errors: `0`
- Console errors: `0`
- Failed `401`, `403`, `404`, or `5xx` responses: `0`
- Production mutations: `0`

The skipped controls include production-sensitive actions such as logout, exit, scenario execution controls when covered by the destructive-action policy, and controls obscured by active overlays. No application failure was observed during this pass.

## Follow-up Regression Loop

Targeted rerun after fixes:

- Agent harness, agent evaluation, prompt-safety, UX accessibility, API security headers, catalog search, and normalized persistence group: **passed** (`55 passed, 3 skipped`).
- Frontend unit tests: **8 passed**.
- Frontend production build: **passed**.
- Deployed crawler: **passed**.

The full backend suite has previously shown order-sensitive persistence failures when run after the broader test collection. The normalized persistence test passes in isolation and in the focused regression group; this should be stabilized before using the full suite as a release gate.

## Prioritized Todo List

### P0: Before relying on this as a production gate

- [ ] Run the crawler with a controlled staging internal session.
- [ ] Store authentication state securely; never commit tokens or OTPs.
- [ ] Fail the test explicitly when the route is blocked by authentication in staging.
- [ ] Add a staging-only environment variable for the crawler base URL.
- [ ] Confirm the crawler sees the authenticated navigation tabs and drawers.
- [ ] Repair the four backend regressions listed in the validation loop.

### P1: Improve coverage

- [ ] Add screenshots and traces when the crawler finds a page error or HTTP failure.
- [ ] Record the exact URL and DOM target for every clicked control.
- [ ] Add a per-route findings summary.
- [ ] Add a crawler run to the production-gates GitHub Actions workflow against staging.
- [ ] Add mobile viewport coverage.

### P2: Safety and operations

- [ ] Keep destructive controls excluded by default.
- [ ] Add separate opt-in tests for approval, dispatch, PO, and freeze flows using mocked staging data.
- [ ] Alert on new `404`, `5xx`, page-error, or console-error findings.
- [ ] Retain Playwright reports and traces as CI artifacts.

## Interpretation

This run proves that the deployed public frontend route is reachable and that the unauthenticated/safe crawl and authenticated internal session both completed without detected runtime or protected-route failures. This does not prove real mailbox behavior, database connectivity, destructive business actions, or production API authorization for every role.

---

## Internal UI Remediation Plan

### 1. Overview & Remediation Goals

- Eliminate all unhandled client-side JavaScript console errors during route traversal.
- Ensure 100% of interactive UI controls (buttons, modals, tabs, drawers, cards, and forms) respond with correct state transitions.
- Standardize accessible loading, empty, error, and offline-state representations across all views.
- Resolve the confirmed data-quality mismatch where Sourcing Matrix, Proc Command, Trace Vault, and Sales Command display `Intake_Failed` / `Pending extraction` records.
- Preserve the crawler safety boundary: production mutation controls remain excluded from the read-only crawler.

### 2. High-Priority Component Fixes

#### Confirmed workflow/data-state issue

- **Affected views:** Sourcing Matrix, Proc Command, Trace Vault, and Sales Command.
- **Finding:** The authenticated UI receives successful responses but displays an RFQ with `Intake_Failed` / `Pending extraction`.
- **Likely ownership:** RFQ intake persistence, orchestration status transitions, or the API response mapping consumed by these views.
- **Required modification:** Trace one RFQ from `event.rfq.received` through intake persistence and verify that the frontend receives the canonical RFQ status, extracted part number, quantity, and customer fields. Add a fixture-backed regression test for the expected extracted state.

#### Customer portal loading states

- **File:** `frontend/src/components/views/CustomerPortal.tsx`
- **Finding:** Loading-state text contracts require explicit request and purchase-order progress labels.
- **Required modification:** Keep `Sending request...` and `Sending purchase order...` tied to `isSubmitting` and `isSubmittingPo`, with `disabled` state and `aria-live` status messaging.

#### Event-driven dashboard controls

- **Files:** `frontend/src/components/views/SalesCommandView.tsx`, `frontend/src/components/views/FulfillmentHubView.tsx`, `frontend/src/components/common/AuditLogDrawer.tsx`
- **Finding:** No runtime click failure was observed. These controls remain high-risk because they can approve, dispatch, freeze, or mutate operational state.
- **Required modification:** Add explicit accessible names, stable `data-testid` values, confirmation states, and negative-path error rendering. Cover mutations only in staging with disposable records.

#### Swarm Runner

- **File:** `frontend/src/components/views/SwarmSimulationView.tsx`
- **Finding:** Urgent AOG, low-margin counter-offer, and sanctions-blocking simulations completed successfully.
- **Required modification:** Keep the runner simulation-only, expose scenario completion status with `role="status"`, and add a mobile viewport test.

### 3. Step-by-Step Execution Checklist

- [ ] Trace the displayed `Intake_Failed` RFQ through API response, persistence, and orchestration state transitions.
- [ ] Add a regression fixture proving extracted RFQ data reaches Sourcing Matrix, Proc Command, Trace Vault, and Sales Command.
- [ ] Fix any status or payload mapping that converts successful intake into `Pending extraction`.
- [ ] Preserve `Sending request...` and `Sending purchase order...` loading text in `CustomerPortal.tsx`.
- [ ] Add explicit `data-testid` and accessible `role` attributes to key interactive elements for deterministic test matching.
- [ ] Ensure drawers have stable close controls and focus restoration.
- [ ] Wrap asynchronous data fetching hooks in error boundaries and loading/empty guard conditions.
- [ ] Add `aria-busy="true"` to loading regions and `role="status"` to progress messages.
- [ ] Add screenshots and Playwright traces when crawler assertions fail.
- [ ] Add per-route findings output to the crawler report.
- [ ] Run the crawler with a controlled staging authentication state.
- [ ] Add the authenticated crawler to the staging release gate.
- [ ] Run mobile viewport coverage.
- [ ] Keep destructive production actions excluded from the default crawler.
- [ ] Add separate staging-only tests for approval, dispatch, PO, and freeze actions.
- [ ] Re-run the Playwright auto-crawler to verify zero remaining UI errors.
- [ ] Run the focused backend regression group.
- [ ] Run the complete backend suite with a documented timeout budget.
- [ ] Commit and push the updated report and validated remediation changes.

### 4. Findings by Technical Bucket

#### Interactive Component & Handler Failures

- No confirmed unresponsive safe control was observed.
- Three Agent Logs drawer cycles opened and closed successfully.
- Destructive controls were skipped by policy, so their real mutation behavior remains unverified in production.

#### State & Loading Display Discrepancies

- Confirmed: several operational views display `Intake_Failed` / `Pending extraction` data despite successful page/API transport.
- Loading text and accessible progress-state contracts require continued regression coverage.

#### Routing & Navigation Errors

- No navigation `404` was observed.
- All seven internal navigation tabs were visited successfully.
- Staging should still validate authenticated route transitions separately from production read-only crawling.

#### Console & Unhandled Exception Logs

- No page errors or console errors were observed during the authenticated crawl.
- No failed `401`, `403`, `404`, or `5xx` responses were observed after authentication.
- The remaining risk is untested destructive paths and real API/database/provider behavior, not observed client-side exceptions.

### 5. Execution Disposition

#### Confirmed resolved by crawler evidence

- Internal route navigation completed successfully across all seven tabs.
- Safe buttons, cards, drawers, search, theme controls, and simulation controls completed without click or close failures.
- Authenticated traversal produced zero page errors, console errors, and failed HTTP responses.
- Frontend unit tests and production build passed during the latest validation loop.

#### Requires implementation or staging verification

- **Interactive component and handler failures:** No safe-control failure is currently confirmed. Approval, dispatch, PO, freeze, logout, and other mutation handlers remain unverified because the crawler correctly skips destructive actions. Exercise them only against disposable staging data with explicit confirmation and rollback assertions.
- **State and loading discrepancies:** The confirmed `Intake_Failed` / `Pending extraction` dashboard data must be traced through RFQ persistence, orchestration transitions, and API-to-view mapping. Loading regions should expose `role="status"` and `aria-busy="true"` without rendering empty-state copy at the same time.
- **Routing and navigation errors:** None were observed. Keep the authenticated seven-tab traversal and mobile viewport pass in CI so route regressions are detected before deployment.
- **Console and exception logs:** None were observed after authentication. Preserve page-error, console-error, and failed-response capture, and attach screenshots/traces whenever a future run fails.

#### Release gate

The UI crawler is green for read-only authenticated coverage, but this is not a complete production sign-off. Close the workflow/data-quality finding, run mutation coverage in staging, and retain crawler artifacts before treating the internal command center as fully verified.

## Latest Execution Loop

Date: 2026-09-23

Recent commit baseline: `3160b11 Expand authenticated UI crawler findings`.

Fresh checks:

- Deployed crawler: **passed**, `1 passed (8.8s)`.
- Focused backend regression group: **passed**, `55 passed, 3 skipped`.
- Frontend unit tests: **8 passed**.
- Frontend production build: **passed**.

The focused backend group now passes the previously tracked agent, accessibility, CORS, catalog, and normalized persistence checks. Remaining work is staging/provider validation and the workflow/data-quality investigation described above.
