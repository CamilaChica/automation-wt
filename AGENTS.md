# Deployment Migration Rules

These rules apply to all deployment automation in this repository.

## Mandatory pre-flight gate

- `scripts/preflight_check.py` must run successfully before any staging or production deployment command.
- Any failed pre-flight check must stop the deployment flow with a non-zero exit code.

## Production safety gate

- Render production deployment triggers and GoDaddy DNS record mutations are forbidden unless explicit approval is provided.
- The required production gate is `APPROVAL_CONFIRMED=true`.
- Any value other than `true` must immediately abort production cutover logic.

## Persistence validation requirement

- Before deployment, scripts must validate that SQLite durability path `/var/data/app.db` is reachable and writable.
- The deployment database must contain required migration tables:
  - `inventory_items`
  - `suppliers`
  - `csv_ingestion_logs`
  - `purchase_orders`

## Credential handling

- Keep Render and GoDaddy credentials in environment variables only.
- Do not hard-code or commit API keys, secrets, deploy hooks, domains, or production endpoints.
