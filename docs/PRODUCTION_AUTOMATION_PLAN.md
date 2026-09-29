# End-User Delivery Plan

**Status: BLOCKED.** The latest observed production `/ready` response was HTTP 503. Keep `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=false`, production workers paused, and customer access closed until the gates below pass in order and the release owner approves go-live.

This is the single source of truth for pending delivery work. Other documentation may describe APIs, architecture, test evidence, or safe operating procedures, but must not maintain a second release checklist. Record only sanitized evidence here; never include credentials, tokens, connection strings, or customer data.

**Already verified, not pending:** the canonical Render database reports Alembic revision `0009_prompt_rag_storage`; do not repeat production migration or seed steps. A fresh disposable PostgreSQL database completed migration lifecycle and clean schema parity checks. Four live local PostgreSQL workflow tests and the isolated backend suite passed. The current local frontend run passed 93 E2E tests with 2 skipped, and the mobile responsiveness diagnostic passed all 54 checks. These mocked/local results are not staging evidence. The September 28 Render export restore is reported complete; content parity with the September 26 reconciliation source remains unverified. Production readiness has not passed, and the local PostgreSQL test database has schema drift.

## Next Steps

1. Finish PostgreSQL persistence and validate migration `0010_reconciliation_quarantine` plus reliability tests on a clean disposable PostgreSQL 18 database.
2. Close reconciliation evidence: compare the September 26 source with the September 28 export, attach the sanitized target dry-run report/conflict metrics, and approve dispositions for 241 quote items and 3 supplier profiles. Do not write before this approval.
3. Pin the candidate, run release frontend checks, and complete staging/customer acceptance.
4. Obtain release/database approval, deploy with workers paused, verify readiness and service ownership, then enable runtime and resume workers gradually.
5. Hand off access and support, archive sanitized evidence, and monitor initial live transactions.

## 1. Preflight and Scope

- [ ] Verify credential rotation and replacement use by the API and every worker. Resolve Render Blueprint/build/start/health-check drift, confirm worker/mailbox ownership, and keep production workers paused.
- [ ] Name release, database, rollback, and incident owners; agree on the maintenance window and rollback trigger. Store production secrets only in the approved secret manager.
- [ ] Confirm only launch-critical providers: attachment storage, Microsoft Graph mailbox identities/permissions, and approved shared rate limiting. Treat Twilio/SMS as deferred unless required for the first accepted workflow. Keep migrations out of automatic builds.

## 2. Candidate and Data Gates

- [x] Backup gate: the release owner reports the September 28 Render export was restored to an isolated target with integrity verified; retain protected evidence. Production is at `0009_prompt_rag_storage`; do not repeat migrations or seed steps.
- [x] Scoped async read refactor: RFQ list/detail (including parent-filtered item/quote records), RFQ audit logs, shipment tracking/list, supplier directory/offer/detail GETs, internal inventory GETs, customer catalog search, and inventory-triggered RFQ resume discovery use async repositories in PostgreSQL mode with the existing local fallback preserved. Focused route/query/worker tests pass. PostgreSQL integration coverage is present but was skipped locally because `TEST_DATABASE_URL` is not configured. This does not complete the wider persistence cutover.
- [ ] Complete PostgreSQL persistence across API, orchestration, communication, and worker paths; preserve transaction/workflow behavior and prove no operational SQLite fallback. Queued quote email must not advance RFQ state until delivery is confirmed `SENT`.
- [ ] Validate migration `0010_reconciliation_quarantine` upgrade, rollback, and schema parity on a clean disposable PostgreSQL 18 database. Then run the required durability, transaction, locking, concurrency, idempotency, and outbox/ambiguous-send tests. The current Windows environment has PostgreSQL 16/17 tools but no Docker/PostgreSQL 18 server; provision an approved disposable PostgreSQL 18 target to complete this gate. Do not apply this migration to production until reviewed and approved.
- [x] Implemented reconciliation rules: valid-parent quote items receive conservative defaults and a review hold; orphans are quarantined inactive; exact duplicates are skipped; incomplete supplier profiles match by tax ID/corporate email domain without overwriting live rows, otherwise quarantine inactive with related offers held. Apply requires explicit disposition approval and a sanitized reference. Implementation is not formal policy approval.
- [ ] Finish reconciliation review: obtain the sanitized target dry-run report and PostgreSQL conflict metrics; verify content parity between the September 26 source and September 28 export; formally approve disposition for the flagged records. Only then may the approved apply run proceed; verify key parity/counts and create a post-reconciliation backup.

**Reconciliation evidence:** source-only `--plan-only` against the September 26 archive mapped 439 RFQs, 242 quote items, and 3 supplier profiles; 241 quote items and all 3 supplier profiles were flagged. Other mapped counts: 37 customers, 1 RFQ item, 255 quotes, 0 live supplier parts, 14 audit events, 377 communications, 0 inbound emails, 1 communication task, 244 review-queue records, and 963 operational records. All 3 supplier profiles and their 3 offers are staged in inactive quarantine pending target identity resolution; no quote items were orphaned. The plan-only run made no PostgreSQL connection. The operator reports zero target-key conflicts, but the sanitized target report and conflict metrics are not attached. Render confirms a September 28 export entry; archive-content parity is not verified.

**Safety posture:** `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=false`; production `/ready` is HTTP 503 while release gates remain incomplete; zero production writes have been executed. Reconciliation dry-run rolls back. Apply is explicit and requires the disposition-approval flag/reference; any target-key collision, schema truncation warning, or FK violation aborts before commit.

## 3. Staging and Acceptance

- [ ] Lock the minimum launch scope: customer frontend is `apps/web`; keep `frontend/` internal. Defer optional endpoints, analytics, maps, and SMS unless the intended customer requires them. Hide or label unsupported/demo data; confirm roles, mobile usability, privacy/terms, retention, and export-control procedures.
- [ ] Pin one candidate commit and run its frontend build, unit, mobile, and browser checks. Existing mocked/local results do not count as staging acceptance.
- [ ] Deploy separate staging API/frontend/workers with disposable PostgreSQL, test storage/mailboxes, and staging domain. Require `/healthz` and `/ready` success, expected migration head, repository/schema probes, no SQLite fallback, healthy mailboxes, and correct worker ownership.
- [ ] Exercise a customer RFQ through quote review and test-mailbox receipt. Verify persisted workflow/outbox records; test customer chases, supplier replay, inventory imports, RFQ resume, unreadable documents, PO duplicate prevention, compliance blocks, delivery failures, timeouts, and repeated submits. Obtain written customer/operator acceptance.

## 4. Production Release and Handoff

- [ ] Obtain release-owner and database-approver sign-off on code/security review, backup, reconciliation, reliability, staging acceptance, and rollback plan.
- [ ] Deploy the exact reviewed commit with workers paused. Confirm database identity/revision, data parity, backup, mailbox health, service ownership, and `/ready` HTTP 200.
- [ ] Enable `OPERATIONAL_POSTGRES_RUNTIME_ENABLED` only after all gates pass. Resume workers gradually; monitor delivery, duplicates, SQLite writes, stuck workflows/outbox, review queues, database errors, and worker health. Pause and roll back on the agreed triggers.
- [ ] Create least-privilege user accounts, provide onboarding/support contacts, archive sanitized approvals and delivery evidence, and monitor initial transactions.

## Deferred Housekeeping

- [ ] Inventory the two synthetic Azure backup artifacts separately from release delivery. Delete only with explicit owner approval and verified recovery evidence; deletion is not a production go-live prerequisite.
