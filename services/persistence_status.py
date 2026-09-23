"""Operational visibility for the current persistence boundary."""

from __future__ import annotations

import os
from pathlib import Path

from services.operations_store import operations_store


def persistence_status() -> dict[str, object]:
    postgres_mirror_enabled = os.getenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "operational_store": "sqlite_compatibility_store",
        "operational_store_path": str(Path(operations_store.path)),
        "inventory_postgres_mirror_enabled": postgres_mirror_enabled,
        "postgres_primary_migration_required": True,
    }