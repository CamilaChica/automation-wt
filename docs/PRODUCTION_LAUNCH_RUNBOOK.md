# Production Launch Runbook

The single ordered release plan is [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md). This file contains operational guidance only; do not maintain a separate launch checklist here.

Production is currently blocked by `/ready` HTTP 503. The production schema is verified at `0009_prompt_rag_storage`; do not run migrations or seed commands as routine deployment steps. Use [RENDER_SHELL_RUNBOOK.md](RENDER_SHELL_RUNBOOK.md) for authorized read-only checks.

## Rollback Procedure

1. Pause autonomous dispatch and outbound email.
2. Suspend mailbox, inventory, outbox, and RFQ-resume workers.
3. Roll back the API and frontend to the last reviewed release.
4. Preserve audit, automation, outbox, and delivery records for investigation.
5. Restore a database backup only after the database owner reviews the data-loss impact and approves the restore.
6. Recheck database identity, schema revision, `/ready`, and authenticated mailbox health before resuming any worker.

Do not resume production services while readiness is failing or the release owner has not approved the recovery.