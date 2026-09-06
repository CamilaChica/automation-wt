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

## Run the Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. Vite proxies frontend requests from `/api` to the local backend at `http://127.0.0.1:8000`.

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
