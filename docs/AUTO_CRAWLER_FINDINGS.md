# Pending UI Crawler Release Gates

Target: `https://winged-tycoons-frontend.onrender.com/internal`

## Deployment and Production Data

- [ ] Reconcile the live `/ready` response before any deployment. Latest observed response was HTTP 200 with `storage_engine=postgresql` while also reporting `operational_store_path=/opt/render/project/src/data/operations.db`; this is not valid proof of PostgreSQL-primary persistence.
- [ ] After the backend readiness/persistence mismatch is resolved, deploy the approved frontend/backend revisions and record their deployed commit/build identifiers. Do not deploy during the current mismatch.
- [ ] Re-run authenticated production RFQ/detail/automation-event/attachment payload assertions after a safe deployment. The last read-only dashboard showed zero active RFQs, so live RFQ field/status behavior is unverified.
- [ ] Verify deployed RFQ state and field preservation end-to-end: intake, persistence, orchestration, API mapping, and dashboard rendering for extracted, pending, and failed states.

## Staging Mutations

- [ ] Run with disposable staging records only: quote approval/dispatch, purchase order, certify/reject, hard freeze, email, supplier add-to-quote, and fulfillment commands.
- [ ] For each mutation, verify confirm/cancel behavior, one submission under repeat clicks, pending/success/failure feedback, persistence, rollback or cleanup, and audit trace.
- [ ] Do not run destructive actions against production. Local browser tests intercept API routes and are not staging evidence.

## Product and Operational Decisions

- [ ] Decide whether intake operations should expose a retry/reprocess API. No such endpoint is currently available; failed RFQs remain blocked from mutations and show escalation guidance.
- [ ] Connect the customer UI's remaining live RFQ, quote, catalog, shipment, sourcing, compliance, and KPI values to verified production API data; keep sample values labeled and do not present them as live.
- [ ] Confirm whether carrier map tiles and external shipment sources are approved for production use, including attribution, availability, and rate limits.

## Verification Gaps

- [ ] Exercise slow-network, timeout, and API-failure behavior against staging services with representative authenticated records.
- [ ] Verify mailbox health and a controlled RFQ-to-quote-to-email lifecycle in the approved staging environment; record message, RFQ, quote, communication, and delivery evidence.
- [ ] Run the latest local slow-network/API-failure regressions against the approved staging build after deployment and record its commit identifier.

## Current Blocker

The current live readiness payload is internally inconsistent about its operational store. No deployment or live/staging mutations were performed for this pass. Keep production release unsigned until PostgreSQL authority and deployed revision are independently verified.
