# AGENTS.md

This repository hosts a multi-agent RFQ-to-Quote platform (FastAPI backend + React frontend). Autonomous code changes must stay scoped, validated, and PR-only.

## Repository map

- `agents/` - Domain agents for intake, parts intelligence, inventory, supplier discovery, compliance, pricing, quote generation, and customer communication.
- `api/` - FastAPI app entrypoint (`api/main.py`) and auth/session support.
- `services/` - Workflow orchestration (`services/orchestration_service.py`), database service, mailbox integrations.
- `models/` - Data models used by API and services.
- `frontend/` - Vite + React + TypeScript dashboard and customer portal.
- `tests/` - Python backend unit tests for workflow and agents.
- `worker.py` - Long-running mailbox polling worker.

## Feature coupling rules

- RFQ flow changes must consider orchestrator state transitions in `services/orchestration_service.py` and endpoint behavior in `api/main.py`.
- Changes touching quote approval/rejection must verify audit logs and approval gates remain consistent.
- Customer-facing changes must preserve role boundaries:
  - `ROLE_CUSTOMER` can only access customer-safe data.
  - Internal inventory, sourcing, approvals, and RFQ operations remain privileged.
- Mailbox behavior changes should account for both `sales` and `purchasing` mailboxes and avoid persisting credentials.
- Pricing/compliance updates should preserve escalation behavior and traceability checks.

## Required verification commands

Run in this exact order after code edits:

1. Backend tests (repository root):
   - `python -m unittest discover -s tests -p "test_*.py"`
2. Frontend lint/type-check (`frontend/`):
   - `npm run lint`
3. Frontend production build (`frontend/`):
   - `npm run build`

## Safety and change policy

- Never push directly to protected branches (`main`, `master`).
- Always work on a feature branch (e.g., `codex/feature-update-<timestamp>`) and open a PR.
- Do not commit secrets, credentials, tokens, or `.env` files.
- Make minimal, targeted edits; do not refactor unrelated areas.
- If verification fails, fix errors and rerun the required checks before requesting review.
