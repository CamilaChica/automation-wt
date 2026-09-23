# Production Automation Plan

**Last verified:** 2026-09-23

## Goal

Move Winged Tycoons from a credible demo workflow to a reliable procurement automation service for messy mail, supplier attachments, repeated follow-ups, PO alerts, and continuous inventory enrichment.

## Execution status

### Live verification

- Render API: `https://winged-tycoons-api.onrender.com/ready` returned HTTP `200`.
- Render frontend: `https://winged-tycoons-frontend.onrender.com/` returned HTTP `200`.
- The application is live and serving traffic.
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
- The operational RFQ/quote/communication store remains SQLite-compatible until its PostgreSQL repository migration is completed.
- Render service disks are service-scoped; `winged-worker` and `winged-inventory-ingestion` do not share the same SQLite supplier database. PostgreSQL must become the shared source of truth before relying on cross-worker supplier state.
- Autonomous outbound email remains subject to existing fail-closed and human-review policies.

## Next production actions

1. Set `INVENTORY_INGESTION_POSTGRES_ENABLED=true` in the deployed `winged-inventory-ingestion` Render worker environment.
2. Confirm `DATABASE_URL` points to the reachable production PostgreSQL instance from that worker.
3. Redeploy the worker and verify `/ready` reports `inventory_postgres_mirror_enabled=true`.
4. Run the live production smoke suite with `LIVE_API_URL` and `LIVE_API_TOKEN`.
5. Migrate RFQ, quote, communication, PO, and audit persistence to PostgreSQL before claiming PostgreSQL-primary production readiness.
