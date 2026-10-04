# Production Launch Runbook

The single ordered release plan is [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md). This file contains operational guidance only; do not maintain a separate launch checklist here.

The production `/ready` read-only check on 2026-10-04 confirmed healthy PostgreSQL at `0012_supplier_offer_received_at` with full operational persistence. This release adds the reviewed, additive migration `0013_database_business_policies`; it creates and seeds an advisory-policy table without changing existing business records. Render's existing API pre-deploy command runs `alembic upgrade head`. Confirm successful rollout from `/ready` current/expected revision `0013_database_business_policies` and each existing service's deployed commit. Preserve managed database backups and the previous release for recovery. Use [RENDER_SHELL_RUNBOOK.md](RENDER_SHELL_RUNBOOK.md) for read-only checks.

## Rollback Procedure

1. Pause autonomous dispatch and outbound email.
2. Suspend mailbox, inventory, outbox, and RFQ-resume workers.
3. Roll back the API and frontend to the last reviewed release.
4. Preserve audit, automation, outbox, and delivery records for investigation.
5. Restore a database backup only after the database owner reviews the data-loss impact and approves the restore.
6. Recheck database identity, schema revision, `/ready`, and authenticated mailbox health before resuming any worker.

Do not resume production services while readiness is failing or the release owner has not approved the recovery.