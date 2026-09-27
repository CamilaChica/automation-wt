# Pending UI Crawler Release Gates

Target: `https://winged-tycoons-frontend.onrender.com/internal`

## Deployment and Production Data

- [ ] Resolve the live `/ready` HTTP 503 gate: production remains disabled until inventory mirroring and the full operational RFQ/supplier/quote repositories are PostgreSQL-backed.
- [ ] After the readiness gate is resolved, deploy the approved frontend/backend revisions and record their deployed commit/build identifiers. Do not deploy while `/ready` returns 503.
- [ ] Re-run authenticated production RFQ/detail/automation-event/attachment payload assertions after a safe deployment. The last read-only dashboard showed zero active RFQs, so live RFQ field/status behavior is unverified.
- [ ] Verify deployed RFQ state and field preservation end-to-end: intake, persistence, orchestration, API mapping, and dashboard rendering for extracted, pending, and failed states.

## Staging Mutations

- [ ] Run with disposable staging records only: quote approval/dispatch, purchase order, certify/reject, hard freeze, email, supplier add-to-quote, and fulfillment commands.
- [ ] For each mutation, verify confirm/cancel behavior, one submission under repeat clicks, pending/success/failure feedback, persistence, rollback or cleanup, and audit trace.

## Product and Operational Decisions

- [ ] Decide whether intake operations should expose a retry/reprocess API. No such endpoint is currently available; failed RFQs remain blocked from mutations and show escalation guidance.
- [ ] Verify the RFQ/detail, supplier-offer, shipment, and automation-event bindings in approved staging. Document state, compliance-file checks, historical SLA, fleet-spend, and annual-savings values remain sample because no persisted read endpoints are available; keep their `SAMPLE / DEMO DATA` badges until those API contracts exist.
- [ ] Confirm whether carrier map tiles and external shipment sources are approved for production use, including attribution, availability, and rate limits.
- [ ] Decide whether to implement a real unread-notification count and dedicated notification feed; neither capability is currently available.

## Verification Gaps

- [ ] Exercise slow-network, timeout, and API-failure behavior against staging services with representative authenticated records.
- [ ] Verify mailbox health and a controlled RFQ-to-quote-to-email lifecycle in the approved staging environment; record message, RFQ, quote, communication, and delivery evidence.
- [ ] Run the latest local slow-network/API-failure regressions against the approved staging build after deployment and record its commit identifier.
- [ ] Verify Q&A answers and role-specific activity names with customer-support and operations owners before production release.

## Current Blocker

The latest observed `GET /ready` response is HTTP 503: production remains disabled until inventory mirroring and the full operational RFQ/supplier/quote repositories are PostgreSQL-backed. Do not deploy or run mutations against production while this gate is unresolved. Local browser tests use mocked APIs and are not staging evidence.
