import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.db_service import MockDatabaseService, db_service
from services.operations_store import OperationsStore, operations_store


class TestNormalizedRFQPersistence(unittest.TestCase):
    def test_quote_line_items_are_persisted_independently(self):
        rfq = db_service.create_rfq("Line Buyer", "line-items@example.com", "Need XYZ123")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        db_service.add_quote_item(
            quote.id,
            "RFQ-ITEM-1",
            "XYZ123",
            2,
            "Inventory",
            50.0,
            50.0,
            0.0,
            "FAA 8130-3",
            "Pass",
            description="Actuator",
            condition="OH",
            lead_time_days=4,
            attachments=["cert.pdf"],
        )

        import sqlite3
        row = sqlite3.connect(operations_store.path).execute(
            "SELECT part_number, description, quantity, condition, certification, lead_time, attachments FROM customer_quote_items WHERE quote_id = ?",
            (quote.id,),
        ).fetchone()

        self.assertEqual(row[:6], ("XYZ123", "Actuator", 2, "OH", "FAA 8130-3", 4))
        self.assertIn("cert.pdf", row[6])

    def test_status_transition_preserves_normalized_business_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            service = MockDatabaseService.__new__(MockDatabaseService)
            service.rfqs = {}
            service.rfq_items = {}
            service.inventory = {}
            service.suppliers = {}
            service.supplier_quotes = {}
            service.quotes = {}
            service.quote_items = {}
            service.audit_logs = {}
            service.shipments = {}
            service.shipment_events = {}

            with patch("services.db_service.operations_store", store):
                rfq = service.create_rfq("Buyer", "buyer@example.com", "Need XYZ123 quantity 2")
                service.add_rfq_item(rfq.id, "XYZ123", 2, condition="OH")
                service.update_rfq_status(rfq.id, "Validating")
                connection = sqlite3.connect(Path(directory) / "operations.db")
                row = connection.execute(
                    "SELECT part_number, quantity, condition_requested, status FROM rfqs WHERE id = ?",
                    (rfq.id,),
                ).fetchone()
                connection.close()

        self.assertEqual(row, ("XYZ123", 2, "OH", "Validating"))


if __name__ == "__main__":
    unittest.main()
