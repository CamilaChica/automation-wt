# Production Automation Plan

**Last verified:** 2026-09-23

## Goal

Move Winged Tycoons from a credible demo workflow to a reliable procurement automation service for messy mail, supplier attachments, repeated follow-ups, PO alerts, and continuous inventory enrichment.

## Execution status

### Live verification

- Render API: `https://winged-tycoons-api.onrender.com/ready` returned HTTP `200`.
- Render frontend: `https://winged-tycoons-frontend.onrender.com/` returned HTTP `200`.
- The application is live and serving traffic.
- The public frontend and API health endpoints respond, but end-user OTP delivery requires a successful Graph `sendMail` operation; a service can be HTTP-healthy while authentication remains unusable.
- The auth UI now exposes Customer Portal and Team Sign In choices before OTP, and failed OTP delivery returns a recoverable error with resend/change-email actions.
- Expired bearer sessions now dispatch an auth-state change so the mounted customer portal returns to sign-in instead of remaining on a dead authenticated screen.
- The readiness response reported `inventory_postgres_mirror_enabled=false`.
- The readiness response reported `postgres_primary_migration_required=true`.

1. **Persistence boundary and release gate**: complete for visibility and safe operation. RFQ, quote, communication, and PO state currently use the SQLite-compatible operational store; supplier inventory and quote mirrors use PostgreSQL when explicitly enabled. Production sign-off must not call this PostgreSQL-only until the operational store is migrated.
2. **Supplier ingestion reliability**: complete. Message-id idempotency, multi-line extraction, attachment context, retryable PostgreSQL mirroring, and missing-field follow-up are implemented.
3. **Extraction and retrieval contracts**: complete. Subject/body/attachment provenance, validated structured output, multi-line preservation, and shared Pydantic state are implemented.
4. **Communication and PO workflow**: complete. Threaded customer responses, supplier discount requests, customer chasing, PO notification, and communication audit records are implemented.
5. **Reliability coverage**: complete for the current runtime boundary. Tests cover attachment-only mail, duplicate handling, multi-line supplier quotes, provider fallback, handoff persistence, customer replies, and failed mirror isolation.
6. **Production cutover**: partially complete. The Render API and frontend are live and healthy, but the deployed ingestion worker is not currently mirroring to PostgreSQL and the operational store has not been migrated from SQLite compatibility storage.

## Current release gate

- `INVENTORY_INGESTION_POSTGRES_ENABLED=true` is required for the dedicated ingestion worker to mirror normalized inventory into PostgreSQL.
- The deployed `/ready` response currently reports `inventory_postgres_mirror_enabled=false`; update the Render worker environment and redeploy it.
- A customer RFQ request that receives HTTP `401` is rejected before the intake handler runs and is not persisted; verify the session before treating the RFQ as received.
- The operational RFQ/quote/communication store remains SQLite-compatible until its PostgreSQL repository migration is completed.
- Render service disks are service-scoped; `winged-worker` and `winged-inventory-ingestion` do not share the same SQLite supplier database. PostgreSQL must become the shared source of truth before relying on cross-worker supplier state.
- Autonomous outbound email remains subject to existing fail-closed and human-review policies.

## Next production actions

1. Set `INVENTORY_INGESTION_POSTGRES_ENABLED=true` in the deployed `winged-inventory-ingestion` Render worker environment.
2. Confirm `DATABASE_URL` points to the reachable production PostgreSQL instance from that worker.
3. Redeploy the worker and verify `/ready` reports `inventory_postgres_mirror_enabled=true`.
4. Run the live production smoke suite with `LIVE_API_URL` and `LIVE_API_TOKEN`.
5. Migrate RFQ, quote, communication, PO, and audit persistence to PostgreSQL before claiming PostgreSQL-primary production readiness.

## Incident Remediation Plan

### Phase 1: Restore customer access and outbound mail

1. In Render, verify `WT_AUTH_ENV=production` and `WT_AUTH_SECRET` is at least 32 characters.
2. Verify Microsoft Graph credentials and mailbox identity for `sales@wingedtycoons.com`.
3. Confirm Graph application permissions include delegated/application access required to send mail and read the sales and purchasing mailboxes.
4. Request one customer OTP and inspect API/worker logs for Graph `sendMail` success or a concrete `401`/`403` error.
5. Keep autonomous quote dispatch disabled until one controlled customer quote reaches the intended mailbox.
6. The API now returns a recoverable HTTP `503` with an explicit verification-email error when Graph/SMTP delivery fails, instead of trapping users in a generic sign-in failure loop.

### Phase 2: Restore supplier ingestion and shared lookup

1. In the `winged-inventory-ingestion` Render worker, set `INVENTORY_INGESTION_POSTGRES_ENABLED=true`.
2. Set a valid production `DATABASE_URL` in that worker and verify it can resolve the private PostgreSQL host from the worker network.
3. Redeploy the ingestion worker.
4. Submit one controlled supplier email with one CSV or PDF attachment.
5. Confirm the worker log shows successful extraction, PostgreSQL upsert, and no fallback to an ephemeral `/tmp` database.
6. Confirm `/ready` reports `inventory_postgres_mirror_enabled=true`.
7. Confirm the API sourcing lookup can see the ingested supplier offer.

### Phase 3: Remove split-brain operational state

1. Add PostgreSQL tables/repositories for RFQs, RFQ items, quotes, quote items, communications, audit events, workflow state, communication tasks, and agent handoffs.
2. Add idempotency keys for inbound message IDs, RFQ creation, quote creation, PO numbers, communication tasks, and supplier quote rows.
3. Run a dual-write period in staging and compare SQLite-compatible state with PostgreSQL state.
4. Switch API and workers to PostgreSQL reads after parity checks pass.
5. Preserve SQLite as a read-only rollback snapshot, then remove it from the production critical path.

### Phase 4: Production sign-off

- Customer OTP request and verification succeeds.
- Customer RFQ email becomes an RFQ record.
- Inventory and supplier lookup return the expected part.
- Missing supplier fields generate a threaded supplier request.
- Customer quote email is delivered and recorded.
- Customer detail request receives an immediate threaded response.
- Supplier discount request and customer chase tasks are scheduled and dispatched.
- Customer PO creates a durable PO record and alerts `camila@wingedtycoons.com`.
- `/ready` is healthy and reports PostgreSQL mirroring enabled.
- No production service uses an ephemeral `/tmp` database for business state.

### Rollback triggers

- OTP emails fail or Graph returns unauthorized responses.
- Supplier ingestion loses message IDs or produces duplicate offers.
- PostgreSQL mirror errors exceed the retry/dead-letter policy.
- Customer or supplier outbound messages are sent to an incorrect recipient.
- PostgreSQL and operational-store records diverge during dual write.

Rollback means disabling autonomous dispatch, pausing mailbox workers, preserving audit events, and returning to the last verified release while the failed gate is investigated.
