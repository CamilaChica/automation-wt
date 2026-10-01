# Production Delivery Plan — Pending Work Only

Single source of truth for what is left before end users can use the app. Completed work is removed; history lives in git.

**Last updated:** 2026-10-01
**Scope:** simple launch. No new features. Anything not required to serve real users today is under "Deferred".
**Status:** 🔴 BLOCKED. Do not sync the Blueprint. Reconcile the listed services, validate only the changed worker, then complete production migration and acceptance. No broad test suite is pending unless a code change requires it.

## Launch checklist (in order)

| # | Item | Owner | Status |
|---|------|-------|--------|
| 1 | Provision Redis and set `REDIS_URL` on backend and email worker | Platform owner | 🔴 Blocked: needs Render access |
| 2 | Set `FORWARDED_ALLOW_IPS` to Render's proxy CIDRs (never `*`) | Platform owner | 🔴 Blocked: needs Render access |
| 3 | Rotate exposed credentials (DB password, Graph/mailbox secrets, API tokens) and store them only in Render env vars | Security owner | 🔴 Blocked: needs credential owner |
| 4 | Suspend the duplicate `backend` and `frontend` services; do not sync Blueprint | Platform owner | 🔴 Blocked: owner action |
| 5 | Apply DB migrations to head (`alembic upgrade head`, adds `0010_shared_auth_state`) | DB owner | 🔴 Blocked: needs prod `DATABASE_URL` |
| 6 | Import auth users: dry run, then `--apply --invalidate-existing-auth --confirm-target` | DB owner | ⏳ Waits on #5 |
| 7 | Deploy; verify `/healthz` = 200 and `/ready` = 200 | Platform owner | ⏳ Waits on #1–#6 |
| 8 | Run prod smoke tests (`tests/test_prod_smoke.py`) against the live URL | Engineering | ⏳ Waits on #7 |
| 9 | Acceptance: one real RFQ → quote → customer view flow, signed off by the business owner | Business owner | ⏳ Waits on #8 |
| 10 | Create end-user accounts and send the login link (customer app: `apps/web`; internal: `frontend/`) | Business owner | ⏳ Waits on #9 |

## Blocked: how to unblock (step by step)

**0. Render service inventory — confirmed by the owner. Do not run Blueprint Sync.**

- **Keep as canonical:** `winged-tycoons-api`, `winged-tycoons-frontend`, `winged-production-db`, `winged-production-redis`.
- **Existing, currently suspended:** `winged-tycoons-email-worker` (sales mailbox + scheduled communication processing) and `winged-inventory-ingestion` (purchasing mailbox/inventory ingestion). These are not Copilot-created duplicates. Resume each only after its env vars and role are confirmed, and only once.
- **Suspend as duplicate aliases:** `backend` and `frontend`. They replace canonical service names in `render.yaml` but have the same API and web roles. Do not delete until confirmed they have no unique URL, traffic, or data.
- **Do not classify as duplicates or delete yet:** `winged-outbox-dispatcher` sends durable queued outbound email; `winged-rfq-resume-worker` processes queued/resumable RFQ events. They are distinct from the mailbox pollers, but not yet proven necessary for today's launch. Keep suspended until the single acceptance flow proves whether the queue paths are needed.
- The `dashboard.render.com/d/dpg-...` link is a Render dashboard URL for a `dpg` resource identifier (database), not another service to delete. Keep `winged-production-db`.

Render Blueprints match services by name. The names `backend` and `frontend` were introduced in place of the existing API/frontend names; do not sync until `render.yaml` is reconciled to the canonical names. In Render, suspend only `backend` and `frontend` now. Keep all databases and disks. Do not remove any worker until its required role is verified.

**A. Redis (`REDIS_URL`), items 1–2. About 10 minutes.**
1. Render Dashboard → New → Key Value (Redis) → same region as the backend → Create.
2. Copy the **Internal** connection URL.
3. Open the backend service → Environment → add `REDIS_URL=<url>`. Repeat for the email worker.
4. On the same backend Environment page, add `FORWARDED_ALLOW_IPS` with Render's proxy CIDRs. If unsure, ask Render support or set it to the load-balancer CIDR shown in Render docs. Do not use `*`.
5. Save. Don't redeploy yet.

**B. Credential rotation, item 3. About 20 minutes.**
1. Postgres: Render → Database → reset the password. Paste the new `DATABASE_URL` into every service that uses it (backend, email worker, ingestion, outbox, resume worker).
2. Microsoft Graph / mailbox: Azure Portal → App registrations → the app → Certificates & secrets → New client secret. Update the secret env var in Render, then delete the old secret.
3. Any other API tokens listed as `sync: false` in `render.yaml`: regenerate each one at its provider and update it in Render.

**C. Blueprint sync: STOP.**
Do not run Manual Sync for this launch. The canonical live names are known; `render.yaml` must be reconciled to `winged-tycoons-api` and `winged-tycoons-frontend` before any future sync. Keep `winged-outbox-dispatcher` and `winged-rfq-resume-worker` suspended until queue requirements are confirmed.

**D. Migration and user import, items 5–6. About 15 minutes, in a quiet window.**
1. Render → backend service → Shell.
2. Run `alembic upgrade head`, then `alembic current`, which should show `0010_shared_auth_state (head)`.
3. Run `python scripts/migrate_auth_users_to_postgres.py`. This is the dry run: check the user count and the target DB it prints.
4. If the output looks right, run `python scripts/migrate_auth_users_to_postgres.py --apply --invalidate-existing-auth --confirm-target`. Users will need to log in again.

**E. Deploy and verify, items 7–8. About 10 minutes.**
1. Trigger Manual Deploy on the backend and workers.
2. `curl https://<backend>/healthz` should return 200, and `curl https://<backend>/ready` should return 200. If `/ready` returns 503, send the response JSON to engineering.
3. Run `python -m pytest tests/test_prod_smoke.py` with the live URL/token env vars set.

**F. Acceptance and onboarding, items 9–10.** The business owner submits one real RFQ, approves the quote, confirms that the customer sees it, and replies "approved". Then create the user accounts.

## Deferred (post-launch, not required today)
- Set `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=true` once PG18 re-verification of the later RFQ stages is done (supplier negotiation, PDF clarification, outbox finalization).
- PG restart-durability drill in a maintenance window.
- SMS, analytics, and maps integrations.
- Azure backup artifact cleanup.
- Historical SQLite → PG data import (canceled).
