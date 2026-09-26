"""Operational visibility for the current persistence boundary."""

from __future__ import annotations

import os

from services.operations_store import operations_store


def persistence_status(*, postgres_healthy: bool = False) -> dict[str, object]:
    postgres_mirror_enabled = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    operational_engine = getattr(operations_store, "storage_engine", "sqlite")
    review_telemetry_postgres = operational_engine == "postgresql"
    # Review/telemetry and event persistence are PostgreSQL-backed, but the full
    # RFQ/supplier business repository layer is not yet migrated.
    postgres_primary = False
    return {
        "operational_store": (
            "postgresql_review_telemetry_only"
            if review_telemetry_postgres and not postgres_primary
            else "postgresql" if postgres_primary else "sqlite_compatibility_store"
        ),
        "operational_store_path": str(operations_store.path) if operations_store.path else None,
        "inventory_postgres_mirror_enabled": postgres_mirror_enabled and postgres_healthy,
        "postgres_primary_migration_required": not postgres_primary,
        "full_operational_persistence_ready": postgres_primary,
        "storage_engine": "postgresql" if postgres_primary else operational_engine,
    }