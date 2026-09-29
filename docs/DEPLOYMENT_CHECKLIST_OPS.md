# Deployment Operations Reference

The ordered pending release work is maintained only in [PRODUCTION_AUTOMATION_PLAN.md](PRODUCTION_AUTOMATION_PLAN.md). Do not track a second checklist here.

The canonical Render database was verified read-only at Alembic revision `0009_prompt_rag_storage`. Production `/ready` remains HTTP 503. Do not run generic migration, seed, reconciliation, deployment, or worker-resume steps from this reference.

For authorized read-only Render shell checks, see [RENDER_SHELL_RUNBOOK.md](RENDER_SHELL_RUNBOOK.md).