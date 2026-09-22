# Render Shell Runbook

This runbook covers the production cutover for the current Azure-only delivery scope. It intentionally excludes Twilio activation and AWS S3 usage.

## Scope

- Azure storage enabled for this delivery
- no Twilio activation in this release
- no AWS S3 bucket requirement in this release
- private Postgres migration and seed happen in the Render shell
- fail-closed LLM behavior remains active when live AI is unavailable

## Prerequisites

- The app has already been deployed to a Render web service or worker service.
- The Render service shell is attached to the same environment as the deployed service.
- `DATABASE_URL` resolves to the private Postgres instance inside Render.
- The app repo is mounted at `/opt/render/project/src`.

## 1) Confirm repo root and environment

```bash
cd /opt/render/project/src
pwd
ls -la
```

## 2) Validate the production environment

```bash
cd /opt/render/project/src
python scripts/verify_production_env.py
```

Expected output:

```text
PRODUCTION_ENV=READY
SECRET_VALUES=NOT_PRINTED
```

## 3) Run Alembic migration

```bash
cd /opt/render/project/src
alembic upgrade head
```

This creates or updates the normalized relational tables such as `aviation_parts`, `supplier_quotes`, `purchase_orders`, and the RFQ item tables.

## 4) Seed the aviation catalog

```bash
cd /opt/render/project/src
python scripts/seed_aviation_parts.py
```

This seeds the baseline parts data needed for sourcing and quotation workflows.

## 5) Post-migration smoke test

```bash
cd /opt/render/project/src
python - <<'PY'
import asyncio
from sqlalchemy import text
from services.async_database import create_engine_from_environment

async def main():
    engine = create_engine_from_environment()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("DB_CHECK=" + str(result.scalar()))
    finally:
        await engine.dispose()

asyncio.run(main())
PY
```

## 6) Health check

```bash
cd /opt/render/project/src
curl --fail --silent --show-error "${API_HEALTH_URL:-http://127.0.0.1:${PORT:-8000}/ready}"
```

## 7) Fail-closed verification

```bash
cd /opt/render/project/src
python - <<'PY'
import os
os.environ['LLM_LIVE_ENABLED'] = 'false'
try:
    from services.email_intelligence import extract_email_intelligence
    extract_email_intelligence('Customer needs part 32-11-45-01', task='rfq_extraction')
    raise SystemExit('FAIL_CLOSED=NO')
except RuntimeError as exc:
    print('FAIL_CLOSED=YES')
    print(str(exc))
PY
```

Expected result:

```text
FAIL_CLOSED=YES
Live LLM extraction is disabled; use deterministic fallback.
```

## 8) Production launcher script

The repo also includes the packaged shell script:

```bash
cd /opt/render/project/src
chmod +x scripts/deploy_production_cutover.sh
./scripts/deploy_production_cutover.sh
```

## Notes

- The runbook intentionally does not enable Twilio in this delivery.
- Azure blob storage is the active cloud storage path for this release.
- If `alembic upgrade head` fails with `socket.gaierror` / DNS resolution errors, the issue is the Render shell environment or private network access, not the repository code.
