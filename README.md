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
- `scripts/` - Utility scripts for local setup and testing workflows
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
requires a long-running worker plan. Do not enable production mode until Graph
mail delivery has passed a smoke test.
Set `FRONTEND_ORIGIN` to the deployed frontend URL and set the frontend
`VITE_API_BASE_URL` to the deployed API URL plus `/api`, for example
`https://winged-tycoons-api.onrender.com/api`.

The mailbox worker validates Graph mailbox connectivity and logs header counts.
It must remain suspended while the API uses development OTP or while Graph
credentials have not been validated.

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

The mailbox adapter in `services/mailbox_service.py` uses the Graph client in
`services/graph_client.py`. Configure `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, and
`GRAPH_CLIENT_SECRET` only in the process environment or Render secret store.
The app uses Graph `Mail.Read` and `Mail.Send` application permissions for the
two shared mailboxes; it does not use IMAP/SMTP Basic Authentication.

For local mailbox testing, register an Entra application, grant admin consent,
set the three Graph variables in the process environment, then run
`python worker.py`. Stop the worker after confirming both mailboxes can be read.
Never commit these values or paste them into chat.

### SMS and freight integrations

Shipment SMS notifications are available through `POST /api/internal/shipments/{shipment_id}/sms`.
They use `services/twilio_service.py` and remain in dry-run mode unless
`TWILIO_ENABLED=true` and `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
`TWILIO_FROM_NUMBER` are configured. Recipient numbers must use E.164 format.

Freight rate lookup is available through `POST /api/internal/freight/quote`.
Configure `FREIGHT_ENABLED=true`, `FREIGHT_API_BASE_URL`, `FREIGHT_API_KEY`, and
optionally `FREIGHT_PROVIDER`. The adapter returns carrier options but does not
modify customer quote totals; shipping remains customer-selected.

ILS, PartsBase, Stripe, FAA, and EASA integrations are intentionally deferred.

### Temporary hosted testing mode

The deployed API may use `WT_AUTH_ENV=development` only for controlled testing.
In that mode the OTP is returned in the API response and displayed in the sign-in
screen, so it is not suitable for real customers. Keep the mailbox worker
suspended in this mode. Before launch, configure Graph OAuth, switch the API to
`WT_AUTH_ENV=production`, verify real OTP delivery, and only then resume the
worker.

### Production launch checklist

See [docs/PRODUCTION_LAUNCH_RUNBOOK.md](docs/PRODUCTION_LAUNCH_RUNBOOK.md) and
[docs/PRODUCTION_DECISIONS.md](docs/PRODUCTION_DECISIONS.md) for the current
deployment decisions, staging gate, rollback procedure, and external launch prerequisites.

1. Register an Entra app and grant least-privilege Graph application permissions
   (`Mail.Read` and `Mail.Send`), then grant admin consent.
2. Enter the tenant ID, client ID, and client secret directly into the Render API
   and worker environment settings.
3. Deploy the API and verify customer and internal OTP delivery by email.
4. Verify sales and purchasing inbox reads and an outbound test message.
5. Resume the worker and monitor its logs through a complete polling interval.
6. Confirm HTTPS/CORS, persistent database storage or backups, health checks,
   support ownership, and a documented rollback to the previous deployment.

Useful frontend commands:

```powershell
npm run build    # Type-check and create a production build
npm run lint     # Run the TypeScript compiler checks
npm run preview  # Preview the production build locally
npm run test:unit # Run Vitest unit/integration suites (frontend/tests)
npm run test:e2e  # Run Playwright browser E2E suites (frontend/tests/e2e)
```

## Run Tests

From the repository root with the virtual environment active:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The tests cover the clean inventory flow, supplier sourcing fallback, compliance escalation, RFQ intake, parts intelligence, and agent behavior.

## Autonomous Testing Architecture

- Repository-level automation instructions are in `AGENTS.md`.
- Third-party services (FedEx, DHL, and e-signature) are mocked with MSW handlers in `frontend/src/testing/msw`.
- Persona E2E coverage exists for Customer, Sales, Procurement, Admin, and Full Autonomous Flow in `frontend/tests/e2e`.
- Copilot browser-testing usage and capability boundaries are documented in `COPILOT_BROWSER_TESTING.md`.

## Mock Testing Quick Start

To run mock testing with mock customers and internal team members:

1. Seed/reset the auth test users:

```powershell
python scripts/seed_mock_test_env.py --reset
```

2. Start backend and frontend (see sections above).
3. Follow the persona runbooks and scenario matrix in `MOCK_TESTING_GUIDE.md`.

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
