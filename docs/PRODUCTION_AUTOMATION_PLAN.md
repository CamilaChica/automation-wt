# Production Delivery Plan

**Last updated:** 2026-10-01
**Scope:** Deliver the existing app with the fewest changes. No unrelated features or repeated test runs.

## Live status checked 2026-10-01

- `https://winged-tycoons-api.onrender.com/healthz`: HTTP 200.
- `https://winged-tycoons-api.onrender.com/ready`: HTTP 503 with the operational PostgreSQL cutover-gate message. In this code path, a missing `DATABASE_URL` or failed PostgreSQL connection returns a different error first. The latest response therefore indicates the database connection passed preflight; the failure is one or more readiness checks: Alembic at head, required operational schema, RFQ/supplier/quote/inventory repository probes, or `INVENTORY_INGESTION_POSTGRES_ENABLED`. The current 503 does not expose which check failed.
- `https://winged-tycoons-frontend.onrender.com/internal`: the existing internal static app is served. The customer portal in `apps/web` is a separate Next.js app and is not declared as a Render service in this Blueprint.
- Render Dashboard is currently at its sign-in page in the available browser session, so no service was suspended, deployed, or otherwise changed in Render.

## Required before customer launch

1. **Resolve the PostgreSQL readiness gate.** Do not recreate the database, change database URLs, or bypass the readiness guard based on this response: the API reached its cutover gate after the connection preflight. The public 503 does not reveal which sub-check failed. In the existing API service's Render Shell, run this once; it is read-only and does not print credentials:

   ```sh
   python - <<'PY'
   import asyncio
   import os
   from services.async_database import create_engine_from_environment, preflight_database, check_migration_state, session_scope
   from repositories.runtime import create_operational_repositories
   from services.operations_store import operations_store

   async def main():
       engine = create_engine_from_environment()
       try:
           await preflight_database(engine)
           print("postgres_preflight=OK")
           print("migrations=", await check_migration_state(engine))
           async with session_scope(engine) as session:
               print("repository_checks=", await create_operational_repositories(session).check_readiness())
           print("operational_schema=", operations_store.check_operational_schema())
           print("inventory_mirroring_env=", os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED"))
       finally:
           await engine.dispose()

   asyncio.run(main())
   PY
   ```

   Apply only the specific confirmed missing migration/schema or setting; preserve production data. Do not rerun app-wide tests for this diagnosis.
2. **Reconcile Render services without creating more aliases.** The Blueprint now names the existing API and internal frontend `winged-tycoons-api` and `winged-tycoons-frontend`. In the Render Dashboard, inspect `backend` and `frontend`; suspend an alias only after confirming it has no unique traffic, data, or configuration. Do not run Blueprint Sync until the live resources have been reconciled.
3. **Deploy the customer portal.** Add/deploy `apps/web` as the customer-facing Next.js app with `API_BASE_URL` set to the HTTPS API origin and `CUSTOMER_PORTAL_ORIGIN` set to its HTTPS public origin. Do not replace the internal static frontend with the customer portal.
4. **Verify one real customer journey.** Confirm a customer can sign in, submit an RFQ, view a sent quote, and submit PO documents; then onboard the intended end users. Do not claim internal PO review is complete: the current API/UI map has an approval endpoint but no pending-PO list endpoint for staff to discover submissions.

## Explicitly deferred by the owner

- Credential rotation (database, mailbox/Graph, and API credentials) is **not a launch gate**. The owner will rotate these after the app has been delivered and is working completely. Do not block delivery on rotation.
- PostgreSQL restart-durability drill, SMS, analytics, maps, backup cleanup, and historical SQLite import.

## Safety and scope

- Do not run Blueprint Sync before checking live service mappings; the wrong service names previously risked creating duplicate Render services.
- Do not suspend or delete an unverified service, database, or disk.
- Do not enable a production workflow mode merely to make `/ready` return 200; the database-backed workflows must actually be ready first.
- Avoid broad/repeated test suites. Run only a targeted check when a code or configuration change requires it, and do not send real customer emails during verification.
