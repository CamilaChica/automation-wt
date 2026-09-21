"""Restore application SQLite databases from a timestamped backup directory."""

import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATABASES = {
    "operations": Path(os.getenv("OPERATIONS_DB_PATH", str(ROOT / "data" / "operations.db"))),
    "supplier_email": Path(os.getenv("SUPPLIER_DATABASE_PATH", str(ROOT / "data" / "supplier_email_store.db"))),
    "auth": Path(os.getenv("WT_AUTH_DB", str(ROOT / "data" / "winged_tycoons_auth.db"))),
}


def restore_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()


def main(backup_dir: str | Path | None = None) -> None:
    if backup_dir is None:
        if len(sys.argv) != 2:
            raise SystemExit("Usage: python scripts/restore_sqlite.py <backup-directory>")
        backup_dir = sys.argv[1]
    backup_path = Path(backup_dir)
    if not backup_path.is_dir():
        raise SystemExit(f"Backup directory does not exist: {backup_path}")
    for name, destination in DATABASES.items():
        source = backup_path / f"{name}.db"
        if source.exists():
            restore_database(source, destination)
            print(f"Restored {name} database")


if __name__ == "__main__":
    main()
