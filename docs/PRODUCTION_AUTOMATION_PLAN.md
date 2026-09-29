# End-User Delivery Plan

**Status: BLOCKED.** The latest observed production `/ready` response was HTTP 503. Keep `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=false`, production workers paused, and customer access closed until the gates below pass in order and the release owner approves go-live.

This is the single source of truth for pending delivery work. Other documentation may describe APIs, architecture, test evidence, or safe operating procedures, but must not maintain a second release checklist. Record only sanitized evidence here; never include credentials, tokens, connection strings, or customer data.

**Already verified, not pending:** the canonical Render database reports Alembic revision `0009_prompt_rag_storage`; do not repeat production migration or seed steps. A fresh disposable PostgreSQL database completed migration lifecycle and clean schema parity checks. Four live local PostgreSQL workflow tests and the isolated backend suite passed. Production readiness has not passed. The existing backup export is incomplete, the local PostgreSQL test database has schema drift, and local Playwright still reports 13 failures.

## 1. Secure and Stabilize Production

- [ ] Verify the reported credential rotation: revoke the exposed PostgreSQL credential and confirm the API and every worker use the replacement. Securely confirm any external deploy-hook callers use the regenerated hook.
- [ ] Resolve Render configuration drift before Blueprint sync or deployment. Reconcile the Blueprint's `unknown type "static"` error and the observed active build/start/health-check commands with the reviewed service configuration. Keep database migrations out of automatic builds.
- [ ] Reconcile the complete Render service inventory with the approved topology. Confirm API and worker separation, shared PostgreSQL target, sales-mailbox ownership by the email worker, purchasing-mailbox ownership by inventory ingestion, and the outbox/RFQ-resume worker services. Keep all production workers paused.
- [ ] Assign the release owner, database approver, rollback owner, incident contact, maintenance window, and rollback trigger. Pin the candidate commit after the remaining code work is complete.
- [ ] Resolve launch-provider scope and remove conflicting deployment assumptions: select the attachment-storage provider, decide whether Twilio/SMS is in scope, confirm Microsoft Graph mailbox identities/permissions, and select Redis or an approved edge service for distributed rate limiting. Store all secrets in the approved secret manager.

## 2. Prove Backup and Restore

- [ ] Restore-test the completed September 28 Render export (`2026-09-29T01_43Z.dir.tar.gz`, SHA-256 `B607D5EB1FE52500D28EF9261B7C719BF6F1BBC6B5257370E162D1198084BF44`). Tar extraction succeeded, and PostgreSQL 17.11 read its 216-entry TOC with 39 public tables, matching the 39 public tables on the live database. Provision an owner-approved isolated PostgreSQL 18 target, then verify schema, data integrity, and application-level reads; record protected retention and restore evidence without recording backup contents or credentials.
- [ ] Do not change production schema or data until the isolated restore and its evidence are approved.

## 3. Finish PostgreSQL Runtime Cutover

- [ ] Complete PostgreSQL persistence across all operational API, orchestration, communication, and worker paths. The supplier facade, readiness probes, and RFQ-list slice are already routed; replace remaining synchronous `db_service` and SQLite-compatible operational calls, including inventory mirroring and scheduled/inbound paths, with shared PostgreSQL repositories.
- [ ] Preserve transaction boundaries and workflow behavior for RFQs, suppliers, quotes, inventory, communications, purchase orders, inbound email, scheduled tasks, and outbox delivery. Ensure queued quote email does not advance RFQ state until delivery is confirmed `SENT`.
- [ ] Prove no operational SQLite fallback is active in the candidate service or any worker. Keep `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=false` until all persistence and reliability gates pass.
- [ ] For any future database metadata change, create/review the migration and validate upgrade, rollback, and schema parity on a disposable database first. Production is already at `0009_prompt_rag_storage`; do not rerun migrations as a generic deployment action.

## 4. Complete PostgreSQL Reliability Tests

- [ ] Run the candidate against an approved disposable PostgreSQL 18 database. The four current live workflow tests passed on local PostgreSQL 16; the pre-existing local `test_db` has schema drift and is not clean migration-parity evidence.
- [ ] Verify restart durability, transaction rollback, row locking, optimistic-version conflicts, concurrent inventory reservation/claims, and multi-process inbound idempotency.
- [ ] Verify outbox deduplication, concurrent claims, retry/backoff, terminal failure, stale-send recovery, and manual resolution of ambiguous delivery. Prove an uncertain external send remains `MANUAL_REVIEW_REQUIRED` and is never blindly resent.
- [ ] Verify supplier reply replay, self-sent message handling, unreadable attachment clarification deduplication, corrected inventory import replay, and exactly-once RFQ resume.
- [ ] Retain deterministic test evidence and confirm readiness/schema probes reflect the exact candidate schema.

## 5. Approve and Reconcile Operational Data

- [ ] Review SQLite-to-PostgreSQL mappings, source/target row counts, conflicts, duplicate policy, deterministic audit-ID mapping, and quarantine rules.
- [ ] Decide and document the manual-review disposition for 241 of 242 quote items missing source, acquisition cost, margin, and compliance fields, plus three supplier profiles missing legacy contact/address fields.
- [ ] Review the two synthetic Azure backup archives and remove them only after explicit owner approval and verified backup restoration.
- [ ] Run reconciliation dry-run against the identity-verified target; review the full report and resolve blocking gaps. Apply only after backup restore, policy/data-gap decisions, and change approval. Verify source-key parity and row counts, then create and verify a post-reconciliation backup.

## 6. Complete Launch-Scope Product and Frontend Work

- [ ] Confirm the production customer frontend is `apps/web` and align release/browser tests with it; keep `frontend/` as the internal command center unless an internal deployment is explicitly approved.
- [ ] Resolve the local Playwright failures (last recorded: 63 passed, 13 failed, 2 skipped) and rerun the relevant frontend build, unit, mobile, and browser checks on the pinned candidate.
- [x] Implement and locally test the existing API-backed internal workflows: quote rejection with comments; purchasing PO review; role-restricted inventory/supplier views; freight quoting; RFQ pause/resume; extraction-review queue; LLM health/telemetry; role-aware mailbox inbox/send; shipment creation, events, tracking, and SMS. These changes are in the internal `frontend/` command center, not the production customer frontend in `apps/web`; mocked/local test evidence does not replace staging or customer acceptance.
- [x] Define and implement a safe, auditable reset for `Intake_Failed` RFQs. Admin/manager reset requires an audited reason, returns the RFQ to `Intake`, and never processes it implicitly; the operator must invoke Process separately. `NEEDS_HUMAN_REVIEW` cannot use this reset and must be resolved through its review queue.
- [ ] Decide whether launch requires a quote collection endpoint, shipment-by-ID endpoint, multi-stage fulfillment milestones, compliance-evidence reads, historical KPIs, carrier maps, or a notification feed. Add backend contracts before building UI against unavailable data; otherwise defer those features.
- [ ] Keep unsupported estimates, supplier metrics, maps, OCR/document panels, workflow milestones, and catalog fallbacks explicitly marked as sample/demo or remove them from customer-facing screens.
- [ ] Confirm role boundaries, failure/loading/success feedback, data refresh behavior, mobile usability, privacy/terms, data retention, and export-control procedures for the approved release scope.

## 7. Validate Staging and Obtain Acceptance

- [ ] Deploy the pinned candidate to separate staging API, frontend, and worker services using a disposable PostgreSQL database, approved test storage, controlled mailboxes, and staging domain. Keep production recipients and production data out of tests.
- [ ] Require staging `/healthz` success, `/ready` HTTP 200, expected Alembic head, all repository/schema probes passing, no SQLite fallback, authenticated healthy sales and purchasing mailboxes, correct worker ownership, and working outbox/RFQ-resume services.
- [ ] Run a controlled customer RFQ through quote review and actual test-mailbox receipt. Verify persisted RFQ, quote, outbox, communication, and delivery records; retain message/RFQ/quote/outbox/communication IDs and final transmission status.
- [ ] Test customer questions/chases, supplier reply replay, complete and incomplete inventory imports, exactly-once resume, unreadable-document clarification, PO review and duplicate prevention, compliance blocks, and failed/ambiguous delivery behavior.
- [ ] Exercise slow-network, timeout, API-failure, confirm/cancel, and repeated-submit behavior with disposable records. Re-run authenticated payload assertions against staging; local mocked browser tests do not count as external delivery evidence.
- [ ] Obtain written acceptance from intended customer and internal roles for access, attachments, quote/PO review, trace visibility, sample-data disclosures, mobile use, support paths, and operator workflow.

## 8. Approve Production Rollout

- [ ] Obtain release-owner and database-approver sign-off on code review, dependency/security checks, backup/restore, reconciliation, PostgreSQL reliability, staging acceptance, and rollback plan.
- [ ] Deploy the exact reviewed commit with workers paused. Verify service configuration, database identity, schema revision, data parity, backup status, authenticated mailbox health, and `/ready` HTTP 200 on that deployment.
- [ ] Enable `OPERATIONAL_POSTGRES_RUNTIME_ENABLED` only after every prior gate passes. Resume workers in stages with a controlled workload; monitor message delivery, duplicates, SQLite writes, stuck workflows/outbox items, manual-review queues, database errors, and worker health.
- [ ] Pause rollout and follow the agreed rollback procedure if readiness regresses, persistence diverges, messages duplicate, or delivery becomes ambiguous. Do not expand access until the production smoke test passes.

## 9. Hand Off to End Users

- [ ] Create named least-privilege accounts and provide the approved production URL, role-specific onboarding, required RFQ fields, supported document types, quote/PO instructions, sample-data limitations, and support/escalation contacts.
- [ ] Train operators on approval queues, mailbox ownership, manual delivery review, backup/restore, incident response, and rollback authority.
- [ ] Archive sanitized approvals, deployment commit, backup/restore evidence, reconciliation report, staging/customer acceptance, readiness and mailbox checks, delivery evidence, and support ownership. Monitor the first live transactions before declaring delivery complete.
