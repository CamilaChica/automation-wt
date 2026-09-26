# Production Release: Pending Items

**Status: BLOCKED.** Do not enable `OPERATIONAL_POSTGRES_RUNTIME_ENABLED`, apply migrations to production, or declare RFQ delivery healthy until all applicable items below have evidence.

## Immediate Security and Access

- [ ] Rotate the PostgreSQL password/connection string in Render and local secret storage. A test traceback exposed the configured connection string; do not reuse it.
- [ ] Restore access to the intended PostgreSQL target from a secure test environment. Local DNS currently cannot resolve the configured Render hostname. Do not infer `localhost` or another host as a production fallback.
- [ ] Verify the new target identity, deployed Render commit, and worker maintenance/pause procedure before any production write.

## Backup and Reconciliation

- [ ] Create and verify a PostgreSQL-native backup before changing production schema or data. `backups/20260926T202815Z` is a local SQLite archive, not a PostgreSQL backup.
- [ ] Review the archived SQLite source mapping: customers 37, RFQs 439, RFQ items 1, quotes 255, quote items 242, suppliers 3, supplier offers 3, audit events 14, communications 377, scheduled tasks 1, and inventory/shipment records 10.
- [ ] Review duplicate/conflicting records and the deterministic legacy audit-ID mapping in `scripts/reconcile_sqlite_to_postgres.py`.
- [ ] Run the reconciliation dry-run against the verified target, review its report, then use `--apply` only after backup approval.
- [ ] Verify source-key parity and row counts after reconciliation; retain the report and a post-migration backup.

## PostgreSQL Runtime and Outbox

- [ ] Apply Alembic head `0005_operations_store_contract` to a disposable PostgreSQL database first; verify migration, restart, rollback, and model/schema parity.
- [ ] Exercise RFQ/customer/quote/supplier/task reads and writes against real PostgreSQL, including row locks, optimistic versions, inventory reservation concurrency, and transaction rollback.
- [ ] Test inbound idempotency with two processes and prove claim plus business writes commit or roll back together.
- [ ] Test outbox deduplication, concurrent claims, retry/backoff, terminal failure, stale-send recovery, and manual resolution of ambiguous delivery. Do not automatically resend when the external provider may already have accepted a message.
- [ ] Verify that all production supplier, inbound email, and scheduled task paths use shared PostgreSQL, not the local SQLite fallback.
- [ ] Verify quote/RFQ state stays pending while email is queued and advances to `Quote_Sent` only after the outbox confirms `SENT`.
- [ ] Keep `OPERATIONAL_POSTGRES_RUNTIME_ENABLED=false` until these integration and concurrency checks pass.

## Render and Mailboxes

- [ ] Confirm the deployed commit and inspect its readiness implementation. The live endpoint currently claims PostgreSQL-primary while reporting `/opt/render/project/src/data/operations.db`; do not accept this as ready.
- [ ] After deploying the reviewed migration/code, verify `/ready` against the exact deployed commit: DB reachable, all required tables present, full runtime enabled, and no SQLite operational path.
- [ ] Authenticate with an approved internal account and verify sales and purchasing mailbox health are both `ok`. Unauthenticated `401` is expected and does not pass this gate.
- [ ] Confirm ownership remains isolated: email worker polls `sales`; inventory worker polls `purchasing`.

## Customer and Supplier Proof

- [ ] Submit one controlled RFQ from an authorized test customer and verify the record, quote, outbox, and communication rows in PostgreSQL.
- [ ] Capture message ID, sender, RFQ ID, quote ID, outbox ID, communication ID, recipient, and final `transmission_status=SENT`.
- [ ] Verify the customer mailbox actually receives the quote. The local Playwright test uses mocked APIs and proves UI behavior only.
- [ ] After disposable PostgreSQL is reachable, run the customer portal flow against the real local API/database and verify persisted RFQ plus outbox rows before production smoke testing.
- [ ] Submit one supplier reply, replay the same Graph message, and verify only one business effect is committed.
- [ ] Verify self-sent sales messages are ignored and unreadable supplier PDFs receive at most one same-thread clarification.

## Validation and Release

- [ ] Run `alembic heads`, `alembic history`, and `alembic upgrade head` against disposable PostgreSQL; then run backend PostgreSQL integration and concurrency suites.
- [ ] Resolve or explicitly waive the unrelated full-suite failure `tests/agents/test_agent_harness.py::test_agent_schema_contract_and_metadata[RFQIntakeAgent]` (empty `permissions`).
- [ ] Deploy a pinned reviewed commit, repeat readiness and authenticated mailbox checks, and retain evidence.
- [ ] Resume workers gradually and monitor duplicate messages, outbox failures, stuck workflows, and actual delivery before signing off.
