# Render Shell: Read-Only Verification

**Production DDL is not a pending task.** The canonical Render database was verified read-only at migration revision `0009_prompt_rag_storage`. Production `/ready` remains HTTP 503, so this runbook must not be used to enable runtime, deploy, seed data, or resume workers. Follow [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md) for the remaining release gates and approvals.

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

Expected current production revision: `0009_prompt_rag_storage`. If the database identity or revision differs, stop and ask the database owner to reconcile it; do not apply migrations from this runbook.

## Service Health

Check liveness and readiness without treating liveness as release approval:

```bash
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' "${API_BASE_URL}/healthz"
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' "${API_BASE_URL}/ready"
```

`OPERATIONAL_POSTGRES_RUNTIME_ENABLED` is `true` on all services in `render.yaml`; `/ready` reports `full_operational_persistence_ready: true` once the PostgreSQL schema checks pass.
