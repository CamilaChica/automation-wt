import unittest

from services.db_service import db_service
from services.procurement_service import ProcurementService


class StubRouter:
    def draft_supplier_rfq(self, part_request: dict) -> dict:
        return {
            "provider": "openai",
            "model": "gpt-4o",
            "fallback_used": False,
            "result": {
                "subject": f"RFQ Request - {part_request['part_number']}",
                "body": "Please quote this part.",
            },
        }


class ProcurementServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.inventory.clear()
        db_service.suppliers.clear()
        db_service.supplier_quotes.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.seed_mock_data()

    def test_out_of_stock_creates_pending_supplier_requests_and_sends_email(self) -> None:
        sent = []

        def fake_sender(mailbox: str, recipient: str, subject: str, body: str, reply_to):
            sent.append(
                {
                    "mailbox": mailbox,
                    "recipient": recipient,
                    "subject": subject,
                    "body": body,
                    "reply_to": reply_to,
                }
            )

        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need parts")
        item = db_service.add_rfq_item(
            rfq_id=rfq.id,
            requested_part="060-1234-00",
            qty=5,
            condition="NE",
        )
        item.resolved_part_number = "060-1234-00"

        service = ProcurementService(ai_router=StubRouter(), database=db_service, email_sender=fake_sender)
        result = service.trigger_out_of_stock_procurement(rfq.id, max_suppliers=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(len(sent), 2)
        self.assertTrue(all(entry["mailbox"] == "purchasing" for entry in sent))

        pending = service.get_pending_procurement_items()
        self.assertEqual(len(pending), 2)
        self.assertTrue(all(entry["status"] == "PENDING_SUPPLIER_RESPONSE" for entry in pending))


if __name__ == "__main__":
    unittest.main()
