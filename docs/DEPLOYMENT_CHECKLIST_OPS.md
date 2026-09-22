# Final Deployment Checklist for Operations

## Delivery scope

- Microsoft Graph, AWS S3, and Twilio production delivery
- live AI is fail-closed when unavailable

## Pre-deployment

- [ ] Confirm Render service is the correct production web service
- [ ] Confirm database is the production private Postgres instance
- [ ] Confirm `WT_AUTH_ENV=production`
- [ ] Confirm `WT_AUTH_SECRET` is set and longer than 32 characters
- [ ] Confirm `DATABASE_URL` is populated and reachable from the Render shell
- [ ] Confirm Microsoft tenant, client, secret, and mailbox address are present
- [ ] Confirm AWS S3 bucket, access key, secret key, and region are present
- [ ] Confirm Twilio account SID, auth token, and from phone number are present
- [ ] Confirm OpenAI key is present and `LLM_LIVE_ENABLED=true`
- [ ] Confirm Azure tenant, client, secret, Graph mailbox user are present
- [ ] Confirm Azure storage connection string and container are present
- [ ] Confirm frontend origin and public app URL are configured

## Render shell migration

- [ ] `cd /opt/render/project/src`
- [ ] `python scripts/verify_production_env.py`
- [ ] `python -m config.env_check`
- [ ] `alembic upgrade head`
- [ ] `python scripts/seed_aviation_parts.py`
- [ ] run database smoke check
- [ ] confirm `ready` endpoint responds

## Safety validation

- [ ] verify fail-closed event when `LLM_LIVE_ENABLED=false`
- [ ] confirm no outbound email sends on LLM outage
- [ ] confirm no ambiguous supplier RFQ is dispatched without live extraction

## Production readiness sign-off

- [ ] Render shell migration completed successfully
- [ ] inventory seed completed successfully
- [ ] database connectivity checked successfully
- [ ] health endpoint is responding
- [ ] Twilio credentials are configured and the provider smoke check is approved
- [ ] AWS S3 upload and presigned download URL checks pass
- [ ] Microsoft Graph mailbox smoke tests pass
- [ ] deployment is ready for operational use

## Follow-up items for next release

- [ ] deeper end-to-end PO and supplier notification validation
- [ ] expanded production RBAC and identity enforcement review
