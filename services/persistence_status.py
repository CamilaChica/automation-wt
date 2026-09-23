"""Operational visibility for the current persistence boundary."""

from __future__ import annotations

import os
from pathlib import Path

from services.operations_store import operations_store


def persistence_status(*, postgres_healthy: bool = False) -> dict[str, object]:
    postgres_mirror_enabled = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    postgres_primary = postgres_healthy and postgres_mirror_enabled
    return {
        "operational_store": "postgresql" if postgres_primary else "sqlite_compatibility_store",
        "operational_store_path": str(Path(operations_store.path)),
        "inventory_postgres_mirror_enabled": postgres_mirror_enabled,
        "postgres_primary_migration_required": not postgres_primary,
        "storage_engine": "postgresql" if postgres_primary else "sqlite",
    }