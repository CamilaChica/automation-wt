"""SQLite schema, migration, and audit-integrity quality gates."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.operations_store import OperationsStore


class TestDataIntegrityAndSchemaMigrations(unittest.TestCase):
    def test_schema_initialization_is_idempotent_and_preserves_state(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "operations.db"
            first = OperationsStore(path)
            first.save({"rfq_id": "RFQ-1", "status": "QUOTE_SENT"})
            second = OperationsStore(path)

            self.assertEqual(second.load(), {"rfq_id": "RFQ-1", "status": "QUOTE_SENT"})
            connection = sqlite3.connect(path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
            finally:
                connection.close()

        self.assertIn("automation_events", tables)
        self.assertIn("communications", tables)
        self.assertIn("operations_state", tables)

    def test_automation_event_round_trip_preserves_result_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            event_id = store.record_automation_event(
                event_type="state_transition",
                entity_type="rfq",
                entity_id="RFQ-1",
                status="FAILED",
                result="before=QUOTE_READY",
                error="simulated crash",
            )
            event = next(item for item in store.list_automation_events() if item["id"] == event_id)

        self.assertEqual(event["result"], "before=QUOTE_READY")
        self.assertEqual(event["error"], "simulated crash")

    @unittest.skip("Versioned migration scripts and Alembic-style replay are not implemented.")
    def test_schema_migration_preserves_historical_records(self):
        pass

    @unittest.skip("Append-only audit triggers/application permissions are not implemented.")
    def test_historical_audit_rows_cannot_be_updated_or_deleted(self):
        pass


if __name__ == "__main__":
    unittest.main()
