import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import backup_sqlite, restore_sqlite


class SqliteBackupRestoreSmokeTests(unittest.TestCase):
    def test_backup_and_restore_round_trip_for_all_core_databases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ops_path = root / "operations.db"
            supplier_path = root / "supplier_email_store.db"
            auth_path = root / "winged_tycoons_auth.db"
            backup_root = root / "backups"

            for db_path in (ops_path, supplier_path, auth_path):
                conn = sqlite3.connect(db_path)
                try:
                    conn.execute("CREATE TABLE IF NOT EXISTS sample (id TEXT PRIMARY KEY, value TEXT)")
                    conn.execute("INSERT OR REPLACE INTO sample (id, value) VALUES (?, ?)", ("row-1", "persisted"))
                    conn.commit()
                finally:
                    conn.close()

            with patch.dict(
                os.environ,
                {
                    "OPERATIONS_DB_PATH": str(ops_path),
                    "SUPPLIER_DATABASE_PATH": str(supplier_path),
                    "WT_AUTH_DB": str(auth_path),
                    "SQLITE_BACKUP_DIR": str(backup_root),
                },
                clear=False,
            ):
                backup_sqlite.DATABASES = {
                    "operations": Path(os.getenv("OPERATIONS_DB_PATH")),
                    "supplier_email": Path(os.getenv("SUPPLIER_DATABASE_PATH")),
                    "auth": Path(os.getenv("WT_AUTH_DB")),
                }
                backup_sqlite.BACKUP_DIR = Path(os.getenv("SQLITE_BACKUP_DIR"))
                backup_sqlite.main()

                backup_dirs = [path for path in backup_root.iterdir() if path.is_dir()]
                self.assertTrue(backup_dirs, "Expected a timestamped backup directory to be created.")
                latest_backup = max(backup_dirs, key=lambda path: path.name)
                self.assertTrue((latest_backup / "operations.db").exists())
                self.assertTrue((latest_backup / "supplier_email.db").exists())
                self.assertTrue((latest_backup / "auth.db").exists())

                restore_sqlite.DATABASES = {
                    "operations": Path(os.getenv("OPERATIONS_DB_PATH")),
                    "supplier_email": Path(os.getenv("SUPPLIER_DATABASE_PATH")),
                    "auth": Path(os.getenv("WT_AUTH_DB")),
                }

                conn = sqlite3.connect(ops_path)
                try:
                    conn.execute("UPDATE sample SET value = 'changed' WHERE id = 'row-1'")
                    conn.commit()
                finally:
                    conn.close()

                restore_sqlite.main(str(latest_backup))

                conn = sqlite3.connect(ops_path)
                try:
                    row = conn.execute("SELECT value FROM sample WHERE id = 'row-1'").fetchone()
                finally:
                    conn.close()

                self.assertEqual(row[0], "persisted")


if __name__ == "__main__":
    unittest.main()
