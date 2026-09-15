# Winged Tycoons RFQ-to-Quote Platform

Winged Tycoons is a prototype aerospace parts procurement platform. It turns an unstructured customer request for aircraft parts into a quote through a multi-agent workflow with inventory lookup, supplier sourcing, compliance checks, pricing, audit logs, and human approval gates.

## Features

- RFQ intake from raw email or request text
- Part and quantity extraction
- Internal inventory and supplier sourcing
- Compliance and traceability checks
- Configurable pricing and margin escalation
- Human-in-the-loop quote approval or rejection
- Agent audit logs for each RFQ
- React dashboard with mock-data fallback when the API is unavailable

## Project Structure

- `agents/` - Specialized workflow agents
- `api/` - FastAPI application and HTTP endpoints
- `config/` - Application and pricing settings
- `data/` - Seed data and mock database storage
- `frontend/` - React, TypeScript, Vite, and Tailwind dashboard
- `models/` - Database models and API data structures
- `services/` - Database and orchestration services
- `tests/` - Backend workflow and agent tests
- `tools/` - Shared tool interfaces

## Requirements

- Python 3.10 or newer
- Node.js 18 or newer
- npm

## Run the Backend

From the repository root, create and activate a virtual environment, then install the backend dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install fastapi uvicorn pydantic
```

Start the API:

```powershell
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`. Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

### Deploying to Render

The repository includes `render.yaml` for the FastAPI web service and a separate
mailbox worker. Create a Render Blueprint from the repository, set every
`sync: false` variable in the Render dashboard, and do not commit a `.env` file.
Set `WT_AUTH_ENV=production` and generate a unique `WT_AUTH_SECRET`. The worker
requires a long-running worker plan; a serverless-only plan cannot poll IMAP.
Set `FRONTEND_ORIGIN` to the deployed frontend URL and set the frontend
`VITE_API_BASE_URL` to the deployed API URL plus `/api`, for example
`https://winged-tycoons-api.onrender.com/api`.

The current worker validates mailbox connectivity and logs header counts. Message
persistence, assignment, and outbound attribution should be enabled only after
the first safe IMAP smoke test succeeds.

## Run the Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Vite proxies frontend requests from `/api` to the local backend at `http://127.0.0.1:8000`.

The customer-facing parts portal is available at `http://localhost:3000/customer-portal` (or `/portal`).
Publish that path behind the Winged Tycoons website navigation, for example as
`https://wingedtycoons.com/customer-portal`. Configure the web host to fall back to
`index.html` for this SPA route. Keep `/api/catalog/search` as the only catalog endpoint
exposed to unauthenticated customers; it intentionally excludes internal costs, serial
numbers, and warehouse locations.

Both application surfaces require role-specific email OTP sign-in. The initial
local admin is `camila@wingedtycoons.com`; development mode returns the OTP in
the API response so the flow can be tested without an email provider. Set
`WT_AUTH_ENV=production` before deployment to disable that behavior.
The API returns `401` for missing/invalid sessions and `403` when a valid user attempts
to cross role boundaries; internal inventory, suppliers, approvals, and RFQ operations
are not exposed to customer-role tokens.

The local mailbox adapter is in `services/mailbox_service.py`. Copy `.env.example`
to a local `.env` or configure equivalent process environment variables. Set
`SALES_EMAIL_PASSWORD` and `PURCHASING_EMAIL_PASSWORD` for the two separate
mailboxes; passwords are never written to SQLite or source code. It reads each
`INBOX` over IMAP on `outlook.office365.com:993` and sends through
`smtp.office365.com:587`. In production, set `WT_AUTH_ENV=production` so OTPs
are sent through the Sales mailbox instead of being returned in API responses.

For local mailbox testing, set the four mailbox variables in the process
environment, then run `python worker.py`. Stop the worker after confirming both
mailboxes can be read. Do not test against production mailboxes until you have
verified the credentials and Microsoft 365 tenant policy.

Useful frontend commands:

```powershell
npm run build    # Type-check and create a production build
npm run lint     # Run the TypeScript compiler checks
npm run preview  # Preview the production build locally
```

## Run Tests

From the repository root with the virtual environment active:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The tests cover the clean inventory flow, supplier sourcing fallback, compliance escalation, RFQ intake, parts intelligence, and agent behavior.

## Relational procurement database architecture

The repository now includes a SQLite relational layer for supplier-linked inventory and client RFQ/PO history:

- Migration: `src/db/migrations/002_relational_schema.sql`
- Seed script: `src/db/seed.py`
- Relational helpers: `services/relational_db.py`
- Autonomous purchasing parser: `services/purchasing_email_parser.py`
- Role-specific query services: `services/role_queries.py`
- Database inspection CLI: `scripts/inspect_database.py`

### Schema entities

- `suppliers`
- `clients`
- `inventory_items` (`supplier_id` FK)
- `client_rfqs` (`client_id` FK, optional `inventory_item_id` FK)
- `purchase_orders` (`client_rfq_id` FK, `supplier_id` FK)
- `purchasing_email_ingestion` (idempotent source-email processing log)

### Local commands

Seed relational schema and mock data:

```powershell
python src/db/seed.py
```

Run parser and role-query tests:

```powershell
python -m unittest tests/test_purchasing_email_parser.py tests/test_role_queries.py
```

Inspect relational database summary:

```powershell
python scripts/inspect_database.py --seed-if-empty
```

Watch the summary refresh every 5 seconds:

```powershell
python scripts/inspect_database.py --watch --seed-if-empty
```

## Autonomous developer agent workflow

This repository includes a first-pass autonomous runner:

- Context and constraints: `AGENTS.md`
- Guardrail policy: `config/autonomous_agent_policy.json`
- Runner package: `agent_runner/`
- GitHub workflow: `.github/workflows/autonomous-agent.yml`

Supported trigger modes:

- Issue label trigger (`auto-implement`) on GitHub issues
- Scheduled cron run (weekly, Monday 04:00 UTC by default)
- Manual dispatch (`workflow_dispatch`)

Required runtime settings:

- `CODEX_COMMAND` (GitHub Actions secret): shell command template used to invoke your Codex executor. It can reference `{prompt_file}` and `{workspace}` placeholders.
- `GITHUB_TOKEN`: provided by GitHub Actions.
- Optional:
  - `DRY_RUN=true|false`
  - `ALLOW_SCHEDULED_WRITES=true|false` (defaults to false for safe scheduled runs)

Behavior notes:

- The runner never writes to protected branches and creates `codex/feature-update-*` branches.
- Verification is enforced after agent edits:
  1. `python -m unittest discover -s tests -p "test_*.py"`
  2. `npm run lint` (frontend)
  3. `npm run build` (frontend)
- If verification fails, the runner retries with diagnostic feedback up to the configured attempt limit.

### Local dry-run simulation (no push / no PR)

Use this to test trigger parsing and artifact generation before enabling writes:

1. Ensure dependencies are installed:
   - Backend: `python -m pip install -r requirements.txt`
   - Frontend: `cd frontend && npm ci`
2. From repository root, run:
   - Issue-label mode: `python scripts/run_agent_dry_run.py --mode issues`
   - Manual dispatch mode: `python scripts/run_agent_dry_run.py --mode workflow_dispatch`
   - Schedule mode: `python scripts/run_agent_dry_run.py --mode schedule`
3. Optional: provide a custom event payload file:
   - `python scripts/run_agent_dry_run.py --mode issues --event data/fixtures/issues_labeled_auto_implement.json`

What this does:

- Uses mode-specific fixtures:
  - `issues`: `data/fixtures/issues_labeled_auto_implement.json`
  - `workflow_dispatch`: `data/fixtures/workflow_dispatch_auto_implement.json`
  - `schedule`: `data/fixtures/schedule_auto_implement.json`
- Forces `DRY_RUN=true`
- Skips git branch writes, push, and PR creation
- Still runs verification commands and writes artifacts under `artifacts/agent-runs/`
- Run summaries should report:
  - `"writes_enabled": false`
  - `"pr_url": null`

## API Overview

- `GET /` - Health and service information
- `POST /api/rfqs/intake` - Submit raw RFQ text
- `GET /api/rfqs` - List RFQs
- `GET /api/rfqs/{rfq_id}` - Retrieve RFQ details, quote data, and audit logs
- `POST /api/rfqs/{rfq_id}/process` - Advance an RFQ through the workflow
- `GET /api/inventory` - List mock inventory
- `GET /api/catalog/search?query=...` - Customer-safe part availability search
- `GET /api/suppliers` - List suppliers
- `GET /api/suppliers/{supplier_id}` - Retrieve a supplier
- `POST /api/quotes/{quote_id}/approve` - Approve and send a quote, optionally with price overrides
- `POST /api/quotes/{quote_id}/reject` - Reject a quote

Example RFQ intake request:

```json
{
  "raw_text": "Please quote part 060-1234-00, quantity 2, for Delta MRO Services."
}
```

## Workflow

The orchestrator moves an RFQ through these stages:

`Received -> Parsing -> Inventory Lookups -> Sourcing -> Compliance Check -> Pricing -> Approval -> Quote Sent`

A compliance exception can halt the workflow at `Compliance_Warning`. Low-margin quotes can require additional review before reaching approval.

## Development Notes

- The backend uses an in-memory mock database seeded from the repository data. It is intended for local development and demonstrations, not production persistence.
- The frontend includes mock fallback data so the dashboard remains usable when the backend is unavailable.
- Pricing defaults are defined in `config/settings.py`, including a 20% target margin and a 10% minimum margin threshold.
- The generated SQLite database path is `data/winged_tycoons_mvp.db` when used by the database service.
