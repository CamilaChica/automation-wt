"""Operational visibility for the current persistence boundary."""

from __future__ import annotations

import os

from services.operations_store import operations_store


def persistence_status(
    *,
    postgres_healthy: bool = False,
    repository_checks: dict[str, bool] | None = None,
    migration_status: dict[str, object] | None = None,
) -> dict[str, object]:
    postgres_mirror_enabled = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    operational_engine = getattr(operations_store, "storage_engine", "sqlite")
    adapter_complete = operational_engine == "postgresql"
    schema_checker = getattr(operations_store, "check_operational_schema", None)
    schema_status = schema_checker() if adapter_complete and postgres_healthy and callable(schema_checker) else {
        "ready": False,
        "missing_tables": ["operational schema check unavailable"] if adapter_complete and postgres_healthy else [],
    }
    runtime_cutover_enabled = os.getenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    required_repositories = {"inventory", "rfq", "supplier", "quote"}
    checks = repository_checks or {}
    repositories_ready = all(checks.get(name) is True for name in required_repositories)
    migration_ready = bool(migration_status and migration_status.get("ready") is True)
    postgres_cutover_ready = bool(
        adapter_complete and postgres_healthy and schema_status["ready"]
        and repositories_ready and migration_ready
    )
    postgres_primary = postgres_cutover_ready and runtime_cutover_enabled
    return {
        "operational_store": (
            "postgresql_store_adapter_runtime_incomplete"
            if adapter_complete and not postgres_primary
            else "postgresql" if postgres_primary else "sqlite_compatibility_store"
        ),
        "operational_store_path": str(operations_store.path) if operations_store.path else None,
        "postgres_store_adapter_complete": adapter_complete,
        "operational_schema_ready": bool(schema_status["ready"]),
        "operational_schema_missing_tables": schema_status["missing_tables"],
        "database_migration_status": migration_status or {"ready": False, "error": "not checked"},
        "operational_postgres_cutover_ready": postgres_cutover_ready,
        "postgres_repository_checks": {
            name: checks.get(name, False) for name in sorted(required_repositories)
        },
        "inventory_postgres_mirror_enabled": (
            postgres_mirror_enabled and postgres_healthy and checks.get("inventory") is True
        ),
        "postgres_primary_migration_required": not postgres_primary,
        "full_operational_persistence_ready": postgres_primary,
        "storage_engine": "postgresql" if postgres_primary else operational_engine,
    }