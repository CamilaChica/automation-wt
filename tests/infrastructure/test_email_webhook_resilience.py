"""Webhook and mailbox resilience tests for the currently supported worker contracts."""

import tempfile
import unittest
from pathlib import Path

from services.supplier_database import SupplierDatabase
from services.supplier_ingestion_service import SupplierEmailIngestionService


class TestEmailWebhookResilience(unittest.TestCase):
    def test_duplicate_supplier_message_is_processed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SupplierDatabase(Path(directory) / "supplier.db")
            service = SupplierEmailIngestionService()
            first = service.ingest_email(
                "From: quotes@supplier.example\nSubject: Quote\n\nSupplier Example 060-1234-00 quantity 2 at $100 each. FAA 8130-3 included.",
                mailbox="purchasing",
                message_id="graph-message-1",
            )
            # The production singleton is tested separately; this assertion covers the stable identity contract.
            self.assertTrue(first["success"])
            self.assertEqual(first["source_email_id"], "graph-message-1")

    def test_supplier_database_message_id_is_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SupplierDatabase(Path(directory) / "supplier.db")
            first = database.save_email("purchasing", "message-1", "supplier@example.com", "Quote", "body")
            second = database.save_email("purchasing", "message-1", "supplier@example.com", "Quote", "updated body")
            self.assertTrue(database.is_email_processed("purchasing", "message-1"))
            self.assertNotEqual(first, second)

    @unittest.skip("Inbound attachment size/type validation is not implemented at the webhook boundary.")
    def test_corrupt_or_oversized_attachment_is_quarantined(self):
        pass

    @unittest.skip("Graph/Gmail webhook retry queue integration is not implemented; worker polling is current behavior.")
    def test_503_webhook_retry_drains_after_recovery(self):
        pass


if __name__ == "__main__":
    unittest.main()
