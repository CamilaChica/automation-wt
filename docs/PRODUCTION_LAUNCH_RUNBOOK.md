# Production Launch Runbook

This runbook is an operational checklist, not a substitute for deployment, legal, or compliance approval.

## Required Decisions

- Select one frontend source of truth: `frontend/` or `apps/web/`.
- Select managed PostgreSQL for shared API and worker state.
- Select Redis or an edge provider for distributed rate limiting.
- Configure Microsoft Graph credentials and mailbox permissions in the secret store.
- Confirm whether billing is manual or integrated with a payment provider.

## Staging Gate

1. Deploy API and worker as separate services with separate process commands.
2. Use a staging database, storage container, mailboxes, and domain.
3. Keep `EMAIL_SEND_ENABLED=false` until mailbox smoke tests pass.
4. Verify `/healthz` and `/ready` from the deployment platform.
5. Run `python -m pytest -q` with external email disabled.
6. Run `npm --prefix frontend run test:unit` and `npm --prefix frontend run build`.
7. Verify OTP, role boundaries, RFQ intake, supplier ingestion, compliance blocking, quote approval, PO submission, and carrier webhook idempotency.
8. Verify backup creation and restore into a clean staging database.

## Production Gate

- `WT_AUTH_ENV=production`
- `WT_AUTH_SECRET` is a unique secret of at least 32 characters
- `RATE_LIMIT_ENABLED=true`
- API and worker use the same durable database
- Worker is not started by the API process
- Graph Mail.Read and Mail.Send permissions have admin consent
- Sales and purchasing mailbox tests pass
- DNS and HTTPS are verified
- Privacy policy, terms, retention, and export-control procedures are published
- Rollback owner and incident contact are assigned

## Rollback

1. Disable autonomous dispatch and outbound email.
2. Suspend the mailbox worker.
3. Roll back the API and frontend release.
4. Preserve audit and automation events.
5. Restore the last known-good database backup only after confirming data-loss impact.
6. Re-run readiness and smoke tests before resuming the worker.
