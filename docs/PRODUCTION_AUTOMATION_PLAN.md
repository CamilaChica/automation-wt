# Production Delivery Plan

**Last updated:** 2026-10-01
**Scope:** Deliver the existing app with the fewest changes. No unrelated features or repeated test runs.

## Live status checked 2026-10-01

- `https://winged-tycoons-api.onrender.com/healthz`: HTTP 200.
- `https://winged-tycoons-api.onrender.com/ready`: HTTP 503; after the auth-schema issue is repaired, this endpoint still reports that the operational PostgreSQL cutover is not ready.
- Render shows the latest API deploy failed because the PostgreSQL authentication schema was missing; the last successful API commit remains live.
- Production DB was at `0009_prompt_rag_storage` before a migration. The old running image advanced it to `0010_reconciliation_quarantine`, which only adds inactive quarantine tables. No existing rows or tables were deleted. The current source needs a linear migration that adds shared auth state after this revision.
- `https://winged-tycoons-frontend.onrender.com/internal`: the existing internal static app is served. The customer portal in `apps/web` is a separate Next.js app and is not declared as a Render service in this Blueprint.
- Render shows the duplicate `backend` and `frontend` aliases are already suspended, as are the email and inventory workers. Keep them suspended unless explicitly needed.

## Required before customer launch

1. **Repair and apply the shared-auth migration.** The migration chain now needs to recognize production revision `0010_reconciliation_quarantine` and add auth tables as `0011_shared_auth_state`. Deploy that chain, apply the migration from the matching deployed image, then recover the API deploy. Do not roll back the additive quarantine tables.
2. **Complete the PostgreSQL production cutover.** Resolve `/ready` only by confirming inventory mirroring and the RFQ, supplier, and quote repositories are PostgreSQL-backed. Do not bypass the readiness guard. Import customer auth users only after reviewing the dry-run target and count.
3. **Reconcile Render services without creating aliases.** The Blueprint now names the existing API and internal frontend `winged-tycoons-api` and `winged-tycoons-frontend`; the `backend` and `frontend` aliases are already suspended. Do not run Blueprint Sync until live mappings are reconciled.
4. **Deploy the customer portal.** Host `apps/web` separately from the internal static frontend, set `API_BASE_URL` to the HTTPS API origin, and set `CUSTOMER_PORTAL_ORIGIN` to its HTTPS public origin.
5. **Verify one real customer journey.** Confirm sign-in, RFQ submission, sent-quote viewing, and PO document submission; then onboard the intended end users. Do not claim internal PO review is complete: the current API/UI map has an approval endpoint but no pending-PO list endpoint for staff to discover submissions.

## Explicitly deferred by the owner

- Credential rotation (database, mailbox/Graph, and API credentials) is **not a launch gate**. The owner will rotate these after the app has been delivered and is working completely. Do not block delivery on rotation.
- PostgreSQL restart-durability drill, SMS, analytics, maps, backup cleanup, and historical SQLite import.

## Safety and scope

- Do not run Blueprint Sync before checking live service mappings; the wrong service names previously risked creating duplicate Render services.
- Do not suspend or delete an unverified service, database, or disk.
- Do not enable a production workflow mode merely to make `/ready` return 200; the database-backed workflows must actually be ready first.
- Avoid broad/repeated test suites. Run only a targeted check when a code or configuration change requires it, and do not send real customer emails during verification.
