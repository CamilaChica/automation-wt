import unittest

from services.supplier_database import supplier_db
from services.supplier_ingestion_service import SupplierEmailIngestionService
from services.db_service import db_service


class TestWorkerIdempotency(unittest.TestCase):
    def setUp(self):
        db_service.reset_supplier_data()

    def test_supplier_message_id_is_stable_and_marked_processed(self):
        email_text = (
            "From: quotes@supplier.example\n"
            "Subject: Quote for 060-1234-00\n\n"
            "Supplier Example\n"
            "060-1234-00 quantity 2 at $100 each. FAA 8130-3 included. Lead time 3 days."
        )
        service = SupplierEmailIngestionService()

        first = service.ingest_email(email_text, message_id="graph-message-123")
        second = service.ingest_email(email_text, message_id="graph-message-123")

        self.assertEqual(first["source_email_id"], "graph-message-123")
        self.assertEqual(second["source_email_id"], "graph-message-123")
        self.assertTrue(supplier_db.is_email_processed("purchasing", "graph-message-123"))


if __name__ == "__main__":
    unittest.main()
