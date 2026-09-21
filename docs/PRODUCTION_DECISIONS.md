# Production Architecture Decisions

Status: approved for staging planning; external provisioning still required.

## Frontend

`apps/web` is the production customer frontend because it is the frontend selected by `render.yaml`. The Vite `frontend/` application remains an internal command-center/development surface until it is either retired or explicitly deployed as a separate internal service.

Required follow-up: align frontend E2E and release checks with `apps/web` before public launch.

## Persistence

Production shared state must use managed PostgreSQL. SQLite remains local/test-only because API and worker services cannot safely share independent local disks.

Required follow-up: create migrations, migrate auth/RFQ/quote/supplier/audit/automation state, and verify restore.

## Rate Limiting

Production rate-limit state must use Redis or the deployment edge. The current in-process limiter is a single-instance safety net and is not the final multi-instance implementation.

Required follow-up: configure Redis-backed counters and preserve `Retry-After` behavior.

## Billing

Initial launch uses manual/offline invoicing and purchase-order acceptance. No payment-provider promises are made to customers until a payment integration is implemented and reconciled with orders.

## Mailboxes

The API and mailbox worker remain separate services. Graph credentials, mailbox permissions, and real delivery must be validated in staging before production email is enabled.
