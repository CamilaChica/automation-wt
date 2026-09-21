import tempfile
import unittest
from pathlib import Path

from services.operations_store import OperationsStore


class TestOperationsStore(unittest.TestCase):
    def test_records_communications_and_automation_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")

            communication_id = store.record_communication(
                entity_type="quote",
                entity_id="QTE-123",
                recipient="buyer@example.com",
                sender="sales@wingedtycoons.com",
                channel="email",
                subject="Quotation QTE-123",
                message="Please review the attached quotation.",
                message_type="outbound",
                status="DRY_RUN",
            )
            event_id = store.record_automation_event(
                event_type="email_dispatch",
                entity_type="quote",
                entity_id=communication_id,
                status="DRY_RUN",
                result="logged",
            )

            import sqlite3

            connection = sqlite3.connect(Path(directory) / "operations.db")
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM communications").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM automation_events").fetchone()[0], 1)
                self.assertTrue(event_id.startswith("AUT-"))
            finally:
                connection.close()

    def test_lists_automation_events_for_activity_feed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            store.record_automation_event(
                event_type="document_verification",
                entity_type="quote",
                entity_id="QTE-1",
                status="FAILED",
                error="Low confidence",
            )

            events = store.list_automation_events(status="FAILED")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["entity_id"], "QTE-1")
        self.assertEqual(events[0]["error"], "Low confidence")

    def test_state_survives_store_reinitialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.db"
            first = OperationsStore(path)
            first.save({"rfq_id": "RFQ-123", "status": "Pending_Approval", "items": ["060-1234-00"]})

            second = OperationsStore(path)

            self.assertEqual(second.load(), {
                "rfq_id": "RFQ-123",
                "status": "Pending_Approval",
                "items": ["060-1234-00"],
            })


if __name__ == "__main__":
    unittest.main()
