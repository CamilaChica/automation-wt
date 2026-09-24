# AGENTS.md

## Test Command Instructions

- Run backend tests: `python -m unittest discover -s tests -p "test_*.py"`
- Run frontend unit/integration tests: `npm --prefix frontend run test:unit`
- Run E2E tests: `npm --prefix frontend run test:e2e`
- List available E2E specs: `npm --prefix frontend run test:e2e:list`
- Run targeted browser flow: `npm --prefix frontend run test:e2e -- --project=chromium --grep "<scenario text>"`
- Run mobile responsiveness diagnostics: `npm --prefix frontend run test:e2e -- e2e/mobile_responsiveness_diagnosis.spec.ts --project=ui-gadgets`
- Run deployed internal auto-crawler: `npm --prefix frontend run test:e2e -- e2e/auto_crawler.spec.ts --project=ui-gadgets`

## Mobile Responsiveness Audit

- The mobile diagnostic covers `375x667`, `390x844`, and `768x1024` across the internal dashboard, sales, sourcing, trace, procurement, and fulfillment views.
- It fails on document overflow, unhandled text clipping, interactive controls below 44px, or browser runtime errors.
- Keep destructive controls disabled or mocked; the diagnostic uses disposable API fixtures and does not mutate production data.

## Autonomous Testing Rules

- Generate deterministic tests that run without human input.
- Mock all third-party dependencies (logistics, e-signature, webhooks) in tests.
- Keep all compliance mock generators ITAR/EAR-aware by validating export-control tags.
- For critical path scenarios, include negative-path assertions (corrupt payloads, timeouts, and compliance blocks).

## Browser Testing Execution Loop

1. Generate or update tests first.
2. Run targeted tests before full suites.
3. If failures occur, patch code/tests based on concrete output and re-run.
4. Keep third-party behavior deterministic via MSW mocks in `frontend/src/testing/msw`.
