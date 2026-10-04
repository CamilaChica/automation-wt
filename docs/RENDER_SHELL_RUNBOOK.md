# Render Shell: Read-Only Verification

**This runbook is read-only.** The production `/ready` check on 2026-10-04 confirmed revision `0012_supplier_offer_received_at` and healthy shared persistence. The production integration release targets additive migration `0013_database_business_policies`. Do not use this runbook to deploy or apply DDL; deployment uses the existing Render API pre-deploy command.

## Safety

- Use only the Render shell attached to the reviewed production service and its current managed environment.
- Never paste or print `DATABASE_URL`, passwords, tokens, or provider secrets.
- Do not run `alembic upgrade`, downgrade commands, seed scripts, reconciliation, or the production cutover launcher from this runbook.
- Any future DDL requires a reviewed release migration, verified restorable backup, approved maintenance window, and database-owner authorization.

## Read-Only Database Check

Only after the release owner confirms the shell and database target, run a read-only query. The connection string is read from the shell environment and is not printed.

```bash
psql "$DATABASE_URL" <<'SQL'
BEGIN READ ONLY;
SELECT current_database() AS database,
       current_setting('transaction_read_only') AS transaction_read_only;
SELECT version_num FROM alembic_version;
ROLLBACK;
SQL
```

Do not assume a current production revision from this document. If the database identity or revision is not confirmed through the authorized read-only check, stop and ask the database owner to reconcile it; do not apply migrations from this runbook.

## Service Health

Check liveness and readiness without treating liveness as release approval:

```bash
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' "${API_BASE_URL}/healthz"
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' "${API_BASE_URL}/ready"
```

`OPERATIONAL_POSTGRES_RUNTIME_ENABLED` is `true` on all services in `render.yaml`; `/ready` reports `full_operational_persistence_ready: true` once the PostgreSQL schema checks pass.
