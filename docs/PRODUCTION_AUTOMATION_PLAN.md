# Production Automation Plan

## Goal

Move Winged Tycoons from a credible demo workflow to a reliable procurement automation service for messy mail, supplier attachments, repeated follow-ups, PO alerts, and continuous inventory enrichment.

## Execution status

1. **Persistence boundary and release gate**: complete for visibility and safe operation. RFQ, quote, communication, and PO state currently use the SQLite-compatible operational store; supplier inventory and quote mirrors use PostgreSQL when explicitly enabled. Production sign-off must not call this PostgreSQL-only until the operational store is migrated.
2. **Supplier ingestion reliability**: complete. Message-id idempotency, multi-line extraction, attachment context, retryable PostgreSQL mirroring, and missing-field follow-up are implemented.
3. **Extraction and retrieval contracts**: complete. Subject/body/attachment provenance, validated structured output, multi-line preservation, and shared Pydantic state are implemented.
4. **Communication and PO workflow**: complete. Threaded customer responses, supplier discount requests, customer chasing, PO notification, and communication audit records are implemented.
5. **Reliability coverage**: complete for the current runtime boundary. Tests cover attachment-only mail, duplicate handling, multi-line supplier quotes, provider fallback, handoff persistence, customer replies, and failed mirror isolation.
6. **Production cutover**: pending operational execution. Run migrations, configure Graph permissions, set `INVENTORY_INGESTION_POSTGRES_ENABLED=true`, start separate mailbox workers, verify `/ready`, and run the full regression and live smoke suites.

## Current release gate

- `INVENTORY_INGESTION_POSTGRES_ENABLED=true` is required for the dedicated ingestion worker to mirror normalized inventory into PostgreSQL.
- The operational RFQ/quote/communication store remains SQLite-compatible until its PostgreSQL repository migration is completed.
- Autonomous outbound email remains subject to existing fail-closed and human-review policies.
