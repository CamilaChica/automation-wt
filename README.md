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

### Deployment readiness automation

Deployment guardrails and launch scripts are in [scripts/](/C:/Users/camil/agy2-projects/my-first-project.worktrees/deployment-readiness-integration-agent/scripts).

- Pre-flight checks: `python scripts/preflight_check.py`
- Staging deploy + UAT gate: `python scripts/deploy_staging.py`
- Production cutover (approval required): `APPROVAL_CONFIRMED=true python scripts/production_cutover.py`

Required environment variables for deployment automation:

- `MIGRATION_SQLITE_PATH` (default `/var/data/app.db`)
- `INTERFACE_BASE_URL` (default `http://127.0.0.1:3000`)
- `GODADDY_API_KEY`
- `GODADDY_API_SECRET`
- `GODADDY_DOMAIN`
- `RENDER_DEPLOY_HOOK` (fallback hook)
- `RENDER_STAGING_DEPLOY_HOOK` (preferred for staging)
- `RENDER_PRODUCTION_DEPLOY_HOOK` (preferred for production)
- `RENDER_PRODUCTION_IP`
- `RENDER_PRODUCTION_HOST`
- `PRODUCTION_URL`

Optional:

- `E2E_CHECK_COMMAND` for compliance/ordering e2e validation in pre-flight.  
  If `E2E_CHECK_COMMAND` is not set, pre-flight looks for a `test:e2e` script in [frontend/package.json](/C:/Users/camil/agy2-projects/my-first-project.worktrees/deployment-readiness-integration-agent/frontend/package.json) and fails if neither is available.
- `STAGING_APP_URL`, `STAGING_CUSTOMER_EMAIL`, `STAGING_SALES_EMAIL`, `STAGING_PROCUREMENT_EMAIL`, `STAGING_ADMIN_EMAIL`
- `CUTOVER_TIMEOUT_SECONDS` (default `1800`)
- `CUTOVER_POLL_SECONDS` (default `15`)

Safety behavior:

- Pre-flight is mandatory for staging and production script flows.
- Production DNS/deploy actions are blocked unless `APPROVAL_CONFIRMED=true`.
- Production cutover script updates GoDaddy A (`@`) and CNAME (`www`) records, triggers Render deploy, then polls until DNS and HTTPS are healthy or timeout occurs.

## Run the Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Vite proxies frontend requests from `/api` to the local backend at `http://127.0.0.1:8000`.

### Publish frontend on GitHub Pages

You can host the static frontend on GitHub Pages and keep the FastAPI backend on Render.

1. In GitHub, enable **Settings -> Pages -> Build and deployment -> Source: GitHub Actions**.
2. Set repository variable `VITE_API_BASE_URL` to your deployed Render API URL plus `/api` (example: `https://winged-tycoons-api.onrender.com/api`).
3. Push to `main` (or run the workflow manually) to run [.github/workflows/deploy-frontend-github-pages.yml](/C:/Users/camil/agy2-projects/my-first-project.worktrees/deployment-readiness-integration-agent/.github/workflows/deploy-frontend-github-pages.yml).

The workflow builds [frontend/](/C:/Users/camil/agy2-projects/my-first-project.worktrees/deployment-readiness-integration-agent/frontend) with a GitHub Pages base path and publishes it to:

`https://<github-username>.github.io/<repository-name>/`

For browser API access, set backend `FRONTEND_ORIGIN` to your GitHub Pages origin (example: `https://<github-username>.github.io`).

### Top-bar connect button

The internal app top bar now includes an **OPEN APP** button. Configure destination URL with:

- `VITE_PUBLIC_APP_URL` (recommended; set this to your GitHub Pages URL)
- For GitHub Pages, use `https://<github-username>.github.io/<repository-name>/?portal=customer`
- If not set, it falls back to `?portal=customer` at the current app base path

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
