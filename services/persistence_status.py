"""Operational visibility for the current persistence boundary."""

from __future__ import annotations

import os

from services.operations_store import operations_store


def persistence_status(*, postgres_healthy: bool = False) -> dict[str, object]:
    postgres_mirror_enabled = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    operational_engine = getattr(operations_store, "storage_engine", "sqlite")
    adapter_complete = operational_engine == "postgresql"
    schema_checker = getattr(operations_store, "check_operational_schema", None)
    schema_status = schema_checker() if adapter_complete and postgres_healthy and callable(schema_checker) else {
        "ready": False,
        "missing_tables": ["operational schema check unavailable"] if adapter_complete and postgres_healthy else [],
    }
    runtime_cutover_enabled = os.getenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    postgres_primary = bool(adapter_complete and postgres_healthy and schema_status["ready"] and runtime_cutover_enabled)
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
        "inventory_postgres_mirror_enabled": postgres_mirror_enabled and postgres_healthy,
        "postgres_primary_migration_required": not postgres_primary,
        "full_operational_persistence_ready": postgres_primary,
        "storage_engine": "postgresql" if postgres_primary else operational_engine,
    }