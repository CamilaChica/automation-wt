# Application Runtime Audit

**Audit date:** 2026-10-04

**Scope:** Live Winged Tycoons portals and API, checked-out application wiring, deployment/test configuration, and the supplied communications corpus.

**Outcome:** The live API reports ready, but the custom-domain internal portal had repeated cross-origin API failures in the audit session. Several passing tests exercise test-only mocks or simplified logic rather than the deployed API. The DSPy corpus packaging risk identified during that session has since been resolved.

**Release review update (2026-10-04):** Commit `46cdc7b2` includes the communications corpus and its loader; commit `7610e7b8` includes bounded OCR inference. Both are pushed to `origin/main` and deployed to the existing production services. Post-deploy API readiness returned HTTP 200 with healthy PostgreSQL and migration `0013_database_business_policies`. The portal CORS and authentication observations below are historical findings, not a fresh verification after those deployments. Supplier ingestion still reported a 2 GB memory failure after the OCR deployment, followed by recovery; memory stability remains unresolved.

## Executive summary

| Priority | Finding | Confidence |
|---|---|---|
| High | `team.wingedtycoons.com` cannot read API responses from `api.wingedtycoons.com` in the observed live session. Several internal dashboard APIs fail with CORS errors while `/ready` reports the database and operational persistence are healthy. | High for impact; medium for the precise deployed cause |
| Resolved | The DSPy communications corpus and loader are tracked and shipped in `46cdc7b2`. The earlier untracked-file release risk no longer applies. | High; confirmed against Git tracking and the deployed release |
| Medium | The Render-hosted frontend logs recurring HTTP 401 errors and occasional CORS errors on `/api/rfqs`. The exact 401 endpoint and whether the page had an expected authenticated session are not established by the captured browser logs. | High that 401s occurred; medium/low for root cause |
| Medium | Audit and UI E2E tests can pass with synthetic API responses and do not demonstrate that the live API, CORS, authentication, or database works. The broad audit mock returns HTTP 200 for all intercepted API routes. | High |
| Low / test gap | The e-signature “timeout” test returns a `webhook_timeout` JSON status immediately; it does not assert a timeout, rejected request, or client timeout behavior. | High |

## Live application observations

### 1. Custom-domain portal API calls are blocked by CORS

The shared live page at `https://team.wingedtycoons.com/internal` repeatedly logged CORS failures when calling `https://api.wingedtycoons.com`. In the captured session, this included:

- `/api/internal/mailboxes/health`
- `/api/internal/extraction-reviews?status=PENDING&limit=100`
- `/api/internal/automation-events?limit=100`
- `/api/internal/mailboxes/sales/inbox`
- `/api/internal/mailboxes/purchasing/inbox`
- `/api/rfqs`

The browser reported that the API response lacked `Access-Control-Allow-Origin`; subsequent requests were blocked as `net::ERR_FAILED`. Errors were observed at `2026-10-04T16:51:45Z` and continued in later polling cycles. This is consistent with the internal portal being unable to load live RFQ, mailbox, extraction-review, and automation data.

The API at `https://api.wingedtycoons.com/ready` returned `status: ready`, healthy database state, PostgreSQL operational storage, current migration `0013_database_business_policies`, and successful inventory/quote/RFQ/supplier repository checks. Thus, the readiness response did not expose the frontend/API-origin problem.

**Configuration discrepancy to resolve:** The frontend is published on `team.wingedtycoons.com` in [render.yaml](./render.yaml#L167), but the API service's explicit `ALLOWED_ORIGINS` and `FRONTEND_ORIGIN` values do not list that hostname ([render.yaml](./render.yaml#L53), [render.yaml](./render.yaml#L159)). The local API code does include `https://team.wingedtycoons.com` in its production-origin defaults and enables credentialed CORS ([api/main.py](./api/main.py#L253), [api/main.py](./api/main.py#L297)). The frontend selects `https://api.wingedtycoons.com/api` for company-domain hosts and sends credentialed requests ([api.ts](./frontend/src/services/api.ts#L42)).

Because the checked-out production CORS helper should allow the team origin when the API is actually running with `WT_ENV=production`, the browser evidence does **not** prove that the current source code simply forgot the origin. It points to a mismatch between the live API's effective environment/deployed revision and the checked-out configuration, or another live proxy/API configuration. Verify the running API revision and effective environment, and explicitly include `https://team.wingedtycoons.com` in the API service's deployed CORS allowlist. Do not use a wildcard: this API enables credentials.

The existing CORS tests verify a local preflight and generic production origin behavior, but do not exercise the actual deployed origin against the running service ([test_api_security_headers.py](./tests/test_api_security_headers.py#L18)).

### 2. Render-hosted frontend shows repeated 401s

The shared `https://winged-tycoons-frontend.onrender.com/internal` page logged repeated HTTP 401 errors, approximately once per minute over the captured interval. It also logged CORS errors on `/api/rfqs` from that frontend origin to `https://winged-tycoons-api.onrender.com`.

The browser capture did not identify the URL for each 401, nor establish whether the page was authenticated. The 401 may be the expected response for an anonymous/expired session, or may indicate a session-cookie, auth-bootstrap, or API-origin issue if a signed-in operator was expected. Treat the recurring failures as unresolved until checked in a known authenticated browser session and correlated to API request logs. Do not infer successful sign-in from the page rendering.

### 3. Readiness is not an end-to-end portal check

The live `/ready` response reports database/persistence health; it does not establish that browser-origin requests pass CORS, that an operator session is valid, or that the portal's data-fetch routes succeed. The live observation demonstrates that `ready` and “portal operational” are not equivalent. Add a safe post-deploy smoke check from each supported frontend origin that verifies a credentialed preflight and a read-only authenticated API request, without weakening production authentication.

## Mocks and tests that are not part of the running application

These are useful test assets, but they do not run inside the deployed browser/API process:

| Asset | What it tests/mocks | Why it is not live-app coverage |
|---|---|---|
| [handlers.ts](./frontend/src/testing/msw/handlers.ts#L10) and [server.ts](./frontend/src/testing/msw/server.ts#L1) | MSW responses for FedEx, DHL, and e-signature endpoints. | The server is started by [third_party_mocks.test.ts](./frontend/tests/integration/third_party_mocks.test.ts#L5); no production entrypoint starts this MSW server. |
| [pricingEngine.ts](./frontend/src/testing/engines/pricingEngine.ts#L17) and [pricing.test.ts](./frontend/tests/sales/pricing.test.ts#L1) | A standalone frontend quote/pricing function and its expected outputs. | The engine is imported by the test, not by a production view or API service. A passing test does not validate the backend's live quote calculation. |
| [procurementEngine.ts](./frontend/src/testing/engines/procurementEngine.ts#L26) and [auto_buy.test.ts](./frontend/tests/procurement/auto_buy.test.ts#L1) | A standalone auto-buy decision helper, with a happy path and condition-mismatch case. | As with pricing, this helper is only imported by the test; it is not wired into the production UI/API path. |
| [mock_data.ts](./frontend/tests/e2e-ui/fixtures/mock_data.ts#L1) | Synthetic RFQs, quote detail, and automation events. | UI Playwright specs intercept API calls and return these in-memory values. They are not database records. |
| [rfqFixtures.ts](./frontend/src/tests/fixtures/rfqFixtures.ts#L1) | Synthetic extracted, pending, and failed RFQ states. | Used by RFQ state unit tests, not the running portal. |
| [api-mocks.ts](./frontend/e2e/audit/api-mocks.ts#L105) | Playwright intercepts all `**/api/**` routes and returns fixture payloads, including a mocked `/ready` response that says storage is `mock`. | This makes the browser audit deterministic, but it can report an all-green-looking API flow while production CORS/auth/API behavior is broken. It is not a live deployment test. |

The standard Playwright config starts only a local Vite development server and targets local test directories ([playwright.config.ts](./frontend/playwright.config.ts#L10), [playwright.config.ts](./frontend/playwright.config.ts#L23)). The Render frontend deployment command builds the static bundle but does not run Playwright or the Vitest suite ([render.yaml](./render.yaml#L163)). This separation is normal for production runtime, but a separate post-deploy smoke test is needed to cover live CORS and auth behavior.

The current CI workflow runs the backend pytest suite, frontend Vitest suite, frontend build, and an agent-liveness probe ([production-gates.yml](./.github/workflows/production-gates.yml#L11)). It does not run the frontend Playwright suites or test the deployed domains. The frontend Vitest tests are therefore CI checks—not code running with the live app.

### Specific mock-test weakness: timeout is asserted as a label, not a timeout

The MSW handler has a `2_500 ms` delayed scenario ([handlers.ts](./frontend/src/testing/msw/handlers.ts#L41)). However, the test overrides that handler with one that immediately returns `{ status: 'webhook_timeout' }` and then only checks that status ([third_party_mocks.test.ts](./frontend/tests/integration/third_party_mocks.test.ts#L41)). It does not verify elapsed timeout behavior, a rejected/aborted request, webhook delivery failure, retry, or fallback. The test name currently overstates what it proves.

## Supplied communications corpus and resolved packaging risk

The supplied [winged_tycoons_communications.json](./data/dspy/winged_tycoons_communications.json) is **not just a disconnected frontend mock**. The committed [dspy_email_programs.py](./services/dspy_email_programs.py) reads it and converts compatible, source-grounded records into DSPy examples. The LLM router invokes that DSPy path for supported task types when `DSPY_ENABLED` is true ([llm_provider.py](./services/llm_provider.py#L260)). The Render manifest sets `DSPY_ENABLED=true` and `LLM_LIVE_ENABLED=true` for the API ([render.yaml](./render.yaml#L89)).

At the original audit, the corpus and loader changes had not yet been committed. Release review now confirms that `git ls-files` includes the corpus and that `46cdc7b2` shipped the implementation and regression tests. All 400 corpus records are read; only compatible, source-grounded scenarios become demonstrations. Live prompting uses at most four relevant examples. This is few-shot prompting, not model-weight fine-tuning.

The corpus remains a required runtime artifact: removing it from a future release can fail relevant requests. Its inclusion in Git resolves the identified omission risk, but local checks and deployment success do not prove live-provider response quality. No paid DSPy optimization or live model evaluation was performed for this release.

The corpus is synthetic demonstration/training data, not a substitute for live communications and not a direct test response fixture. Avoid placing real mailbox content or secrets in it; validate synthetic/export-control constraints as required by the project test guidance.

## Verification performed

- **Live API readiness:** passed at both observed API hosts; PostgreSQL and operational repository checks reported healthy.
- **Live custom-domain portal:** failed to read several API endpoints due to browser-reported CORS errors.
- **Live Render-hosted portal:** repeated HTTP 401s observed; exact endpoint/session root cause remains unconfirmed.
- **Frontend Vitest:** passed, **6 test files / 31 tests** (`npm --prefix frontend run test:unit`).
- **Frontend production build:** passed (`npm --prefix frontend run build`).
- **Targeted backend tests:** passed, **15 tests** (`tests/test_api_security_headers.py` and `tests/test_dspy_email_programs.py`).
- **Not run:** full backend test suite, Playwright E2E suite, or production mutation flows. No production data or destructive action was issued.

The original audit added only this report and left the then-uncommitted application changes untouched. The release review updated this report to distinguish those historical observations from the subsequently committed and deployed DSPy/OCR changes. Installed dependency files and generated test results are excluded from the review commit.

## Recommended next steps

1. **Restore live portal/API interoperability:** inspect the deployed API revision and effective `WT_ENV`/CORS settings; explicitly allow `https://team.wingedtycoons.com`; redeploy, then test a credentialed preflight and read-only endpoint from the real portal origin.
2. **Resolve 401s using an authenticated session:** correlate one portal 401 with API logs and verify cookie scope, `SameSite`/`Secure`, session validity, and CSRF bootstrap. Keep this separate from the anonymous page behavior.
3. **Preserve DSPy artifact reproducibility (packaging resolved):** keep the committed corpus in future releases; separately evaluate live response quality without treating synthetic demonstrations as proof of production behavior.
4. **Add post-deploy checks:** run a non-mutating browser smoke test against each deployed frontend/API origin. Keep fixture-driven browser tests, but label them as mocked UI coverage and separately report the live checks.
5. **Correct the timeout test:** make it assert a real elapsed timeout/failure path and the application's retry/fallback behavior rather than returning a timeout-shaped success response.
