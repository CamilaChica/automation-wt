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
