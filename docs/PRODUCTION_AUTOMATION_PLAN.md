# Production Automation Plan

## 1. Shared PostgreSQL Operational State

- Route these entities through shared async PostgreSQL repositories:
  - RFQs and RFQ items
  - Supplier offers
  - Quotes and quote items
  - Communications
  - Audit events
  - Workflow state
  - Communication tasks
  - Inbound-message idempotency
  - Agent handoffs
- Use the same `DATABASE_URL` for:
  - `backend`
  - `winged-tycoons-email-worker`
  - `winged-inventory-ingestion`
- Complete Alembic migrations through `0003_shared_operational_state`.
- Keep `0002_supplier_quote_inv_fields` at 32 characters or fewer.
- Keep `version_table_column_length=255` in both Alembic modes.
- Production must fail if PostgreSQL is missing or unreachable.
- SQLite is allowed only for isolated local tests; never for production business state.

## 2. Render Configuration

Set these variables on all applicable services:

```text
DATABASE_URL=<Render managed PostgreSQL URL>
ALLOWED_ORIGINS=https://winged-tycoons-frontend.onrender.com,https://wingedtycoons.com,http://localhost:5173,http://localhost:3000
```

Set these worker variables:

```text
INVENTORY_INGESTION_POSTGRES_ENABLED=true
GRAPH_MAILBOX_USER_SALES=sales@wingedtycoons.com
GRAPH_MAILBOX_USER_PURCHASING=purchasing@wingedtycoons.com
OPERATIONS_DB_PATH=/var/data/operations.db
SUPPLIER_DATABASE_PATH=/var/data/supplier_email_store.db
```

Worker ownership:

- `winged-tycoons-email-worker` polls only `sales`.
- `winged-inventory-ingestion` polls only `purchasing`.

## 3. Readiness and CORS

- `/ready` must perform a live PostgreSQL check.
- In production, return HTTP `503` if PostgreSQL is missing, unreachable, or mirroring is disabled.
- A successful production response must include:

```json
{
  "status": "ready",
  "postgresql_mirroring": true,
  "storage_engine": "postgresql",
  "postgres_primary_migration_required": false
}
```

- Parse `ALLOWED_ORIGINS` dynamically.
- Allow credentials, all required methods, all required headers, and `OPTIONS` preflight.
- Verify local and production CORS preflight behavior.

## 4. Supplier and Mailbox Safety

- Initialize supplier storage lazily.
- If an explicitly configured local/container path is unwritable, fall back to `/tmp/data` only outside production business-state paths.
- Never use `/tmp` as production operational storage.
- Ignore messages sent by `sales@wingedtycoons.com` to prevent self-reply loops.
- Read only Inbox messages for RFQ ingestion.
- Process each Graph message ID once.
- Reject supplier quote references as part numbers.
- If a supplier PDF is unreadable, request quote details in the same email body thread.
- Exclude supplier offers older than 30 days from automatic pricing and request threaded confirmation.

## 5. UI and Workflow State

- Keep loading and empty states mutually exclusive.
- Add accessible labels, `role="status"`, `aria-busy`, keyboard interaction, and stable selectors.
- Ensure RFQ metadata reaches intake as structured `customer_name` and `customer_email`.
- Trace any `Intake_Failed` or `Pending extraction` RFQ through persistence, orchestration, API mapping, and dashboard views.
- Keep destructive crawler actions disabled by default; test them only with disposable staging data.

## 6. Verification

Run locally:

```text
alembic heads
alembic history
alembic upgrade head
python -m pytest -q
npm --prefix frontend run test:unit
npm --prefix frontend run lint
npm --prefix frontend run build
```

Verify Render:

```text
GET /healthz -> 200
GET /ready -> 200 with PostgreSQL-primary fields above
GET /api/internal/mailboxes/health without auth -> 401
GET /api/internal/mailboxes/health with an approved internal session -> sales and purchasing status=ok
```

Run one new RFQ from `camilachica1991@gmail.com` to `sales@wingedtycoons.com` and capture:

```text
message_id
sender
rfq_id
pipeline_status=Quote_Sent
quote_id=QTE-*
communication_id
transmission_status=SENT
recipient=camilachica1991@gmail.com
```

## Release Gate

Do not mark the application ready until:

- All operational domains use shared PostgreSQL repositories.
- `/ready` reports PostgreSQL as primary.
- Both mailbox health checks pass with an authenticated internal session.
- A new RFQ reaches `Quote_Sent`.
- The communication record reports `transmission_status=SENT`.
- The customer receives the response.
