# Production Delivery Plan — Pending Work Only

Single source of truth for what is left before end users can use the app. Completed work is removed; history lives in git.

**Last updated:** 2026-10-01
**Scope:** simple launch. No new features. Anything not required to serve real users today is under "Deferred".
**Status:** 🔴 BLOCKED. The code is ready on `main` (tests green). Every remaining item needs owner access to Render, Postgres, Redis, or mailbox credentials.

## Launch checklist (in order)

| # | Item | Owner | Status |
|---|------|-------|--------|
| 1 | Provision Redis and set `REDIS_URL` on backend and email worker | Platform owner | 🔴 Blocked: needs Render access |
| 2 | Set `FORWARDED_ALLOW_IPS` to Render's proxy CIDRs (never `*`) | Platform owner | 🔴 Blocked: needs Render access |
| 3 | Rotate exposed credentials (DB password, Graph/mailbox secrets, API tokens) and store them only in Render env vars | Security owner | 🔴 Blocked: needs credential owner |
| 4 | STOP: clean up duplicate Render services before any Blueprint sync (see section 0) | Platform owner | 🔴 Blocked: duplicates are running |
| 5 | Apply DB migrations to head (`alembic upgrade head`, adds `0010_shared_auth_state`) | DB owner | 🔴 Blocked: needs prod `DATABASE_URL` |
| 6 | Import auth users: dry run, then `--apply --invalidate-existing-auth --confirm-target` | DB owner | ⏳ Waits on #5 |
| 7 | Deploy; verify `/healthz` = 200 and `/ready` = 200 | Platform owner | ⏳ Waits on #1–#6 |
| 8 | Run prod smoke tests (`tests/test_prod_smoke.py`) against the live URL | Engineering | ⏳ Waits on #7 |
| 9 | Acceptance: one real RFQ → quote → customer view flow, signed off by the business owner | Business owner | ⏳ Waits on #8 |
| 10 | Create end-user accounts and send the login link (customer app: `apps/web`; internal: `frontend/`) | Business owner | ⏳ Waits on #9 |

## Blocked: how to unblock (step by step)

**0. Duplicate Render services. Do this first and do NOT run Blueprint Sync until it is done.**
Why: Render Blueprints match services by `name`. Commits renamed services in `render.yaml`: `winged-tycoons-api` → `winged-api` → `backend`, `winged-tycoons-frontend` → `frontend`, and `winged-customer-web-2` was added then removed. Workers were also added: `winged-inventory-ingestion`, `winged-outbox-dispatcher`, `winged-rfq-resume-worker`. On each sync Render created a new service for each new name and left the old one running. Old and new workers then poll the same mailbox and DB, so emails and RFQs get processed twice. Workers missing env vars (Redis/DB) also restart or retry forever.
1. Render Dashboard → list all services. For each role, keep ONE: API, frontend, email worker, inventory ingestion, outbox dispatcher, RFQ resume worker.
2. Keep the service that owns the live URL (e.g. `winged-tycoons-frontend.onrender.com`). **Suspend** (don't delete yet) the duplicates.
3. Tell engineering the exact names you kept. `render.yaml` will be renamed to match them, so the next sync updates in place instead of creating new services.
4. After 24h with no issues, delete the suspended duplicates. Detach disks only after confirming they hold no needed data.

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

**C. Blueprint sync, item 4. About 5 minutes.**
1. Render Dashboard → Blueprints → this repo → **Manual Sync**.
2. Review the diff Render shows (services, disks, env keys), then Apply.

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

