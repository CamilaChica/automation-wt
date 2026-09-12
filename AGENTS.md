# AGENTS.md

## Test Command Instructions

- Run backend tests: `python -m unittest discover -s tests -p "test_*.py"`
- Run frontend unit/integration tests: `npm --prefix frontend run test:unit`
- Run E2E tests: `npm --prefix frontend run test:e2e`

## Autonomous Testing Rules

- Generate deterministic tests that run without human input.
- Mock all third-party dependencies (logistics, e-signature, webhooks) in tests.
- Keep all compliance mock generators ITAR/EAR-aware by validating export-control tags.
- For critical path scenarios, include negative-path assertions (corrupt payloads, timeouts, and compliance blocks).
