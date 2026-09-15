import unittest

from services.db_service import db_service
from services.sales_automation_service import SalesAutomationService


class StubRouter:
    def verify_compliance(self, part_data: dict) -> dict:
        del part_data
        return {
            "provider": "anthropic",
            "model": "claude-3.5-sonnet",
            "fallback_used": False,
            "result": {"compliant": True, "certificate_type": "FAA 8130-3"},
        }

    def draft_sales_email(self, quote_data: dict) -> dict:
        return {
            "provider": "openai",
            "model": "gpt-4o",
            "fallback_used": False,
            "result": {
                "subject": f"Quote for {quote_data['part_number']}",
                "body": "Thanks for your RFQ. Please review quote details.",
            },
        }


class SalesAutomationServiceTests(unittest.TestCase):
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

    def test_generate_quote_and_move_to_quoted(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need part")
        item = db_service.add_rfq_item(rfq.id, "060-1234-00", 1, condition="NE")
        item.resolved_part_number = "060-1234-00"

        sent = []
        service = SalesAutomationService(
            ai_router=StubRouter(),
            database=db_service,
            email_sender=lambda *args, **kwargs: sent.append({"args": args, "kwargs": kwargs}),
        )
        result = service.generate_customer_quote(rfq.id)

        self.assertEqual(result["status"], "PO Pending")
        self.assertIn("quote_id", result)
        self.assertEqual(db_service.get_rfq(rfq.id).status, "PO Pending")
        quote = db_service.get_quote(result["quote_id"])
        self.assertIsNotNone(quote)
        self.assertGreater(quote.total_amount, 0)
        self.assertTrue(result["auto_sent"])
        self.assertEqual(len(sent), 1)

    def test_manual_status_pipeline_transition(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need part")
        service = SalesAutomationService(ai_router=StubRouter(), database=db_service)

        service.advance_rfq_status(rfq.id, "Quoted")
        service.advance_rfq_status(rfq.id, "PO Pending")
        out = service.advance_rfq_status(rfq.id, "Solved")

        self.assertEqual(out["status"], "Solved")
        self.assertEqual(db_service.get_rfq(rfq.id).status, "Solved")


if __name__ == "__main__":
    unittest.main()
