#!/usr/bin/env bash
set -euo pipefail

: "${LIVE_API_URL:?LIVE_API_URL must point to the deployed API}"

python scripts/verify_production_env.py
python -m config.env_check
alembic upgrade head
python -m unittest tests.test_api_authorization

ready_url="${LIVE_API_URL%/}/ready"
ready_body="$(curl --fail-with-body --silent --show-error --location "$ready_url")"
printf '%s\n' "$ready_body"
READY_BODY="$ready_body" python - <<'PY'
import json
import os

payload = json.loads(os.environ["READY_BODY"])
if payload.get("status") != "ready" or payload.get("database", {}).get("healthy") is not True:
    raise SystemExit("/ready did not report a healthy database")
PY

printf '%s\n' "Production deployment verification passed."
