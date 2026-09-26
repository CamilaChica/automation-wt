# Winged Tycoons Aero-Procurement Command Center

Winged Tycoons is an aerospace procurement application with a customer parts portal and an internal operations dashboard. Its FastAPI backend and React/Vite frontend support RFQ intake, inventory and supplier workflows, compliance review, quote operations, and fulfillment. Production readiness remains gated; a healthy page or API response alone does not prove that an RFQ was persisted or a customer email was delivered.

## What this project does

- Accepts customer RFQ requests through the customer portal and configured email intake
- Extracts part numbers, quantity, urgency, and delivery context
- Checks internal inventory and supplier sources
- Validates compliance and traceability requirements
- Provides internal sales, sourcing, procurement, trace, and fulfillment views
- Supports quote review, approval, rejection, and audit tracking
- Offers customer-safe catalog search, RFQ submission, purchase-order upload, and shipment tracking flows
- Supports 12 customer portal languages, including Arabic right-to-left layout

## Repository overview

- `api/` — FastAPI application and HTTP API routes
- `agents/` — orchestration and agent implementations for intake, sourcing, pricing, and compliance
- `services/` — database, workflow orchestration, and supporting integrations
- `models/` — data models for RFQs, quotes, suppliers, and audit logs
- `data/` — seed data and mock persistence assets
- `config/` — runtime settings and pricing defaults
- `frontend/` — Vite + React + TypeScript dashboard and portal
- `tests/` — workflow and regression coverage
- `docs/` — runbooks, launch notes, and user guidance

## Architecture

- Backend: Python + FastAPI
- Frontend: React + TypeScript + Vite + Tailwind
- Workflow model: multi-agent processing with human approval and escalation gates
- Local development: SQLite-compatible operational stores and seeded/mock data are used by parts of the application
- Production persistence: PostgreSQL models and repositories exist, but full runtime wiring and live integration are not yet verified; consult the release gate below

## Local quick start

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm

### Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at:

- http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The dashboard is served at:

- http://localhost:3000

The frontend proxies `/api` requests to the local FastAPI server.

## Testing

Python test suite:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Frontend tests:

```powershell
cd frontend
npm run test:unit
npm run test:e2e
```

Use the repository test commands in [AGENTS.md](AGENTS.md) and the detailed local evidence in [docs/AUTO_CRAWLER_FINDINGS.md](docs/AUTO_CRAWLER_FINDINGS.md). The recorded UI and unit-test results are local/mock verification, not proof of production database or email behavior.

## Core workflows

### Internal operations flow

1. Receive RFQ
2. Parse request details
3. Check internal inventory
4. Source alternate suppliers when inventory is insufficient
5. Run compliance and traceability checks
6. Price the proposal
7. Require a human approval or rejection step
8. Send the final quote and update audit logs

### External customer flow

- Customer signs in to the customer portal, searches the customer-safe catalog, or submits an RFQ
- The request enters internal sourcing and review; additional supplier or compliance work may be required
- A submission acknowledgement means the request was accepted by the intake endpoint, not that a quote was generated or sent
- Purchase orders and shipment tracking are available for supported records and require the relevant quote, documents, or tracking token

## Important support docs

- [docs/internal-user-qa.md](docs/internal-user-qa.md) — guidance for internal sales, procurement, and operations users
- [docs/external-user-qa.md](docs/external-user-qa.md) — guidance for external customers
- [docs/PRODUCTION_LAUNCH_RUNBOOK.md](docs/PRODUCTION_LAUNCH_RUNBOOK.md) — production launch and operational checklist
- [docs/PRODUCTION_AUTOMATION_PLAN.md](docs/PRODUCTION_AUTOMATION_PLAN.md) — current production execution plan and risk notes
- [docs/AUTO_CRAWLER_FINDINGS.md](docs/AUTO_CRAWLER_FINDINGS.md) — local UI verification and outstanding release gates

## Release status

**Not signed off for production.** Local frontend, backend, accessibility, and mocked mutation checks are documented in the crawler report. Live production RFQ payload semantics, staging mutation/rollback behavior, PostgreSQL-primary runtime readiness, and end-to-end customer email delivery remain unverified or blocked. The production automation plan dated 2026-09-26 is the operational source of truth; do not treat an earlier `/ready` response or cached dashboard data as proof of a completed persistence cutover. Keep production deploys and worker changes gated until the plan's release gates pass.

Failed RFQs currently show escalation guidance. The UI does not provide an explicit retry/reprocess operation, and failed RFQs have quote, sourcing, and trace mutations disabled.

## Notes

- Local dashboard sample data is explicitly labeled; do not present sample shipment routes or statuses as live telemetry.
- Use [docs/PRODUCTION_LAUNCH_RUNBOOK.md](docs/PRODUCTION_LAUNCH_RUNBOOK.md) and [docs/PRODUCTION_AUTOMATION_PLAN.md](docs/PRODUCTION_AUTOMATION_PLAN.md) before deploying or enabling customer-facing messaging and workers.
- Keep credentials and connection strings in environment or deployment secret stores. Never commit `.env` files or share secret values in support requests.
- Customer access is at `/customer-portal` (also `/portal`); internal staff access is at `/internal`. Local Vite serves the frontend on port 3000 and proxies `/api` to `127.0.0.1:8000`.
