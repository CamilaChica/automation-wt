import unittest
from unittest.mock import patch

from services.mailbox_service import health_check_mailboxes
from services.supplier_ingestion_service import SupplierEmailIngestionService
from services.db_service import db_service


class ProductionMailboxAndSupplierSmokeTests(unittest.TestCase):
    def setUp(self):
        db_service.reset_supplier_data()

    def test_health_check_mailboxes_reports_each_mailbox_state(self):
        with patch(
            "services.mailbox_service.fetch_inbox_messages",
            side_effect=[
                [{"mailbox": "sales", "message_id": "msg-1", "from": "buyer@example.com", "subject": "RFQ", "body": "Need quote for 060-1234-00"}],
                [{"mailbox": "purchasing", "message_id": "msg-2", "from": "quotes@apexaero.com", "subject": "Quote for 060-1234-00", "body": "Part Number: 060-1234-00\nQuantity available: 10\nUnit price: $1,100.00\nFAA 8130-3 certificate included\nLead time: 3 days"}],
            ],
        ):
            health = health_check_mailboxes(["sales", "purchasing"])

        self.assertEqual(health["sales"]["status"], "ok")
        self.assertEqual(health["sales"]["message_count"], 1)
        self.assertEqual(health["purchasing"]["status"], "ok")
        self.assertEqual(health["purchasing"]["message_count"], 1)

    def test_supplier_ingestion_smoke_accepts_realistic_quote_email(self):
        email_text = """
        From: quotes@apexaero.com
        Subject: Quote for 060-1234-00

        Apex Aero Components LLC
        Part Number: 060-1234-00
        Quantity available: 10
        Unit price: $1,100.00 each
        FAA 8130-3 certificate included.
        Lead time: 3 days.
        """

        result = SupplierEmailIngestionService().ingest_email(email_text)

        self.assertTrue(result["success"])
        self.assertEqual(result["part_number"], "060-1234-00")
        self.assertEqual(result["quantity_available"], 10)
        self.assertEqual(result["unit_cost"], 1100.0)


if __name__ == "__main__":
    unittest.main()
