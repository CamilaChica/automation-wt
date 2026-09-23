# Production Automation Plan

**Last verified:** 2026-09-23

**Execution checkpoint:** Focused production gates pass (39 tests previously, plus the current mailbox/supplier checks); frontend lint and production build pass; changed Python modules compile. The full backend suite currently reports four unrelated failures: agent schema-contract validation, a UX loading-text expectation, CORS preflight from `http://localhost:5173`, and normalized SQLite fixture persistence. Live API and frontend return HTTP `200`; `/ready` returns `ready`, but still reports `sqlite_compatibility_store`, `inventory_postgres_mirror_enabled=false`, and `postgres_primary_migration_required=true`. The protected mailbox health endpoint returns `401` without an internal session, so live mailbox connectivity and outbound delivery remain unverified.

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
	The PostgreSQL mirror now preserves searchable quantity, condition, certificate, lead time, location, warranty, and trace-document fields; the customer catalog searches that mirror when enabled.
3. **Extraction and retrieval contracts**: complete. Subject/body/attachment provenance, validated structured output, multi-line preservation, and shared Pydantic state are implemented.
4. **Communication and PO workflow**: complete. Threaded customer responses, supplier discount requests, customer chasing, PO notification, and communication audit records are implemented.
5. **Reliability coverage**: complete for the current runtime boundary. Tests cover attachment-only mail, duplicate handling, multi-line supplier quotes, provider fallback, handoff persistence, customer replies, and failed mirror isolation.
6. **Production cutover**: partially complete. The Render API and frontend are live and healthy, but the deployed ingestion worker is not currently mirroring to PostgreSQL and the operational store has not been migrated from SQLite compatibility storage.

## Current release gate

- `INVENTORY_INGESTION_POSTGRES_ENABLED=true` is required for the dedicated ingestion worker to mirror normalized inventory into PostgreSQL.
- The deployed `/ready` response currently reports `inventory_postgres_mirror_enabled=false`; update the Render worker environment and redeploy it.
- A customer RFQ request that receives HTTP `401` is rejected before the intake handler runs and is not persisted; verify the session before treating the RFQ as received.
- The operational RFQ/quote/communication store remains SQLite-compatible until its PostgreSQL repository migration is completed.
- Render service disks are service-scoped; `winged-tycoons-email-worker` and `winged-inventory-ingestion` do not share the same SQLite supplier database. PostgreSQL must become the shared source of truth before relying on cross-worker supplier state.
- Autonomous outbound email remains subject to existing fail-closed and human-review policies.

## End-to-end customer email incident: current understanding

The required customer outcome is:

```text
external customer -> sales@wingedtycoons.com -> RFQ intake -> supplier sourcing -> quote -> customer email
```

For `camilachica1991@gmail.com`, the log below proves only that the sales mailbox message was read and an RFQ record was created:

```text
Sales mailbox message ... ingested as RFQ RFQ-720302
```

It does **not** prove that a supplier quote existed, that a customer quote was generated, or that outbound mail succeeded. The worker now logs `pipeline_status`, `quote_id`, and `error`; those fields are required evidence for the final outcome.

### What is working

- Microsoft Graph client-credential authentication succeeds.
- The corrected email worker is `winged-tycoons-email-worker` and polls only `sales`.
- Graph message retrieval explicitly requests `body`; previously it fetched headers without the body and silently skipped RFQs.
- Sales messages are deduplicated by Graph message ID.
- Supplier PDF text extraction, quote-reference filtering, 30-day freshness checks, and threaded clarification requests are implemented.
- The source branch contains the fixes through commits `34a4c35`, `fda9713`, and `e67a33f`.

### Why a customer can still receive no response

1. **Supplier wait is not customer dispatch.** Unknown or unavailable parts return `Supplier_Request_Sent`; the system asks suppliers for pricing and does not email the customer until a usable supplier offer exists.
2. **The two workers have separate disks.** `winged-tycoons-email-worker` writes RFQs and operational state to its `/var/data`; `winged-inventory-ingestion` writes supplier offers and attempts to resume RFQs from its own different `/var/data`. These are not shared filesystems. The ingestion worker therefore cannot reliably see the RFQ created by the email worker or resume its pipeline.
3. **SQLite is still in the critical path.** `/ready` previously reported `/opt/render/project/src/data/operations.db`, `inventory_postgres_mirror_enabled=false`, and `postgres_primary_migration_required=true`. A healthy HTTP endpoint does not prove shared RFQ, supplier, or communication state.
4. **Outbound dispatch has separate prerequisites.** `EMAIL_SEND_ENABLED=true` is necessary but not sufficient. Graph application permissions, mailbox identity, and `sendMail` authorization must succeed; the pipeline must reach `Quote_Sent`.
5. **Old processed messages are not new tests.** A `skipped already processed message` line means the exact Graph message ID has already been handled. It is not evidence that the latest client email was read or replied to.

## Required fixes before claiming customer-ready automation

### P0: Establish one shared production state

Choose one of these designs and implement it completely:

- **Preferred:** migrate RFQs, RFQ items, quotes, quote items, communications, audit events, workflow state, tasks, supplier offers, and message idempotency to PostgreSQL; both workers use the same `DATABASE_URL` and repository.
- **Temporary diagnostic option:** run all RFQ processing and supplier ingestion in one worker using one persistent disk. This is not the preferred scalable architecture, but it removes the split-brain failure while PostgreSQL migration is completed.

Do not rely on separate SQLite disks for cross-worker workflows.

### P0: Make the customer delivery contract observable

For every sales message, persist and log:

- source message ID
- sender and subject
- RFQ ID
- pipeline status
- supplier request count and supplier thread IDs
- quote ID, when created
- outbound communication ID
- transmission status (`SENT`, `DRY_RUN`, or failure)
- failure reason and retry/dead-letter state

The customer-facing success condition is only:

```text
pipeline_status=Quote_Sent quote_id=QTE-* transmission_status=SENT recipient=camilachica1991@gmail.com
```

### P0: Add a durable resume mechanism

When a supplier reply is ingested, resume the matching RFQ through shared state using the part number, RFQ association, and supplier thread. Do not depend on the supplier worker importing the email worker's in-memory `db_service` or reading a different local SQLite file.

### P1: Harden mailbox configuration

- Keep `winged-tycoons-email-worker` as the only owner of `sales`.
- Keep `winged-inventory-ingestion` as the only owner of `purchasing`.
- Configure explicit `GRAPH_MAILBOX_USER_SALES=sales@wingedtycoons.com` and `GRAPH_MAILBOX_USER_PURCHASING=purchasing@wingedtycoons.com`; do not rely on the generic variable.
- Set `MAILBOX_FETCH_LIMIT=100` and retain sender/subject in deduplication logs.
- Set Azure SDK loggers to warning level after diagnostics are complete to avoid noisy credential traces.

### P1: Verify outbound mail independently

Run a controlled test that does not depend on OTP:

1. Send a new email from `camilachica1991@gmail.com` to `sales@wingedtycoons.com` with a known catalog part.
2. Confirm the sales worker creates one RFQ with the original sender.
3. Confirm the pipeline reaches `Quote_Sent` or clearly reports `Supplier_Request_Sent`.
4. If `Quote_Sent`, confirm a communication record has `recipient=camilachica1991@gmail.com` and `transmission_status=SENT`.
5. Confirm delivery in the customer mailbox, including spam/quarantine.

No test is successful if it ends at `ingested as RFQ` or `Mailbox sales: read ...`.

### P1: Add failure-state tests

Required automated cases:

- Graph returns a message body and attachment; sales RFQ is parsed.
- Graph returns a message with no body; the worker logs and retains a retryable failure.
- Unknown part creates supplier outreach but does not falsely claim a customer quote was sent.
- Supplier reply in a different worker resumes the original RFQ through shared persistence.
- Supplier quote older than 30 days triggers threaded confirmation to multiple suppliers.
- Quote dispatch failure is recorded and retried without creating duplicate customer quotes.
- Two RFQs from the same customer create two independent RFQs and two independent outbound outcomes.

### Latest test loop result

- `python -m pytest tests/test_worker_mailbox_ownership.py tests/test_supplier_freshness.py tests/test_supplier_email_ingestion.py tests/test_rfq_intake_agent.py tests/test_auth_production_env.py tests/test_customer_reply_pipeline.py -q`: passed.
- `npm --prefix frontend run lint`: passed.
- `npm --prefix frontend run build`: passed.
- `python -m py_compile` for worker, mailbox, ingestion, orchestration, intake, and supplier modules: passed.
- `python -m pytest -q`: four failures remain outside the production email path; they are listed in the execution checkpoint above and must be triaged before a global green build is claimed.
- Live `/healthz` and frontend: HTTP `200`.
- Live `/ready`: healthy HTTP response, but PostgreSQL-primary readiness is not met.

## Next production actions

1. Set `INVENTORY_INGESTION_POSTGRES_ENABLED=true` in the deployed `winged-inventory-ingestion` Render worker environment.
2. Confirm `DATABASE_URL` points to the reachable production PostgreSQL instance from that worker.
3. Redeploy the worker and verify `/ready` reports `inventory_postgres_mirror_enabled=true`.
4. Run the live production smoke suite with `LIVE_API_URL` and `LIVE_API_TOKEN`.
5. Migrate RFQ, quote, communication, PO, and audit persistence to PostgreSQL before claiming PostgreSQL-primary production readiness.

### No-shell Render migration procedure

Do not use Render Shell for the normal deployment path. The `backend` service already runs the migration automatically during every deployment:

```text
pip install -r requirements.txt && alembic upgrade head
```

Use the Render Dashboard instead:

1. Open the `backend` service for this repository.
2. Confirm `DATABASE_URL` is configured in Environment.
3. Select **Manual Deploy** -> **Deploy latest commit**.
4. Wait for the build log to show `alembic upgrade head` completed successfully.
5. Confirm the health check is green at `/ready`.
6. Deploy `winged-inventory-ingestion` from the same commit after the backend migration succeeds.

This migration runs against PostgreSQL during the Render build and does not call the LLM or consume model tokens. Render Shell is only a troubleshooting fallback, not a required step.

The `winged-inventory-ingestion` service is an existing separate Render worker declared in `render.yaml`. It is not a new database; it continuously polls `purchasing@wingedtycoons.com`, parses supplier messages and attachments, and mirrors normalized rows to PostgreSQL when its `DATABASE_URL` and `INVENTORY_INGESTION_POSTGRES_ENABLED=true` are configured.

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
8. Run the Alembic `0002_supplier_quote_inventory_fields` migration before enabling the mirror in production.

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
