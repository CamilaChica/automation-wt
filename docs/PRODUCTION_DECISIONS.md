# Production Architecture Decisions

Status: approved for staging planning; external provisioning and production release gates remain.

## Frontend

`apps/web` is the production customer frontend because it is the frontend selected by `render.yaml`. The Vite `frontend/` application remains an internal command-center/development surface until it is either retired or explicitly deployed as a separate internal service.

The selected frontend and remaining release checks are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Persistence

Production shared state must use managed PostgreSQL. SQLite remains local/test-only because API and worker services cannot safely share independent local disks. The production database is verified at migration head `0009_prompt_rag_storage`; migration creation and application are not pending tasks.

The remaining repository cutover, data reconciliation, restore, and reliability work is tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Rate Limiting

Production rate-limit state must use Redis or the deployment edge. The current in-process limiter is a single-instance safety net and is not the final multi-instance implementation.

The remaining rate-limit provider decision and validation are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).

## Billing

Initial launch uses manual/offline invoicing and purchase-order acceptance. No payment-provider promises are made to customers until a payment integration is implemented and reconciled with orders. No payment integration is currently in the release scope.

## Mailboxes

The API and mailbox worker remain separate services. The remaining credential, permission, ownership, and staging-delivery checks are tracked in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md).
