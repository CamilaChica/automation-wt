#!/usr/bin/env bash
set -euo pipefail

# Run this from the Render API Shell, where the private PostgreSQL hostname resolves.
# Secrets are validated by presence only and never printed.

python scripts/verify_production_env.py
alembic upgrade head
python scripts/seed_aviation_parts.py

python - <<'PY'
import asyncio
import os
from services.async_database import create_engine_from_environment

async def check_database():
    from sqlalchemy import text
    engine = create_engine_from_environment()
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    await engine.dispose()

asyncio.run(check_database())
print("POSTGRES_CONNECTIVITY=OK")
PY

curl --fail --silent --show-error "${API_HEALTH_URL:-http://127.0.0.1:${PORT:-8000}/ready}"
printf '\nPRODUCTION_CUTOVER=READY\n'
