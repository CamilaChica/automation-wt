import unittest
from unittest.mock import patch

from services.email_intelligence import EmailIntelligenceExtraction, ExtractedEmailItem
from services.supplier_database import supplier_db
from services.supplier_ingestion_service import SupplierEmailIngestionService


class TestIngestionReliability(unittest.TestCase):
    def test_multi_line_supplier_quote_is_preserved(self):
        extraction = EmailIntelligenceExtraction(
            email_type="supplier_quote",
            supplier_name="Multi Line Supplier",
            supplier_email="quotes@multi.example",
            confidence_score=0.98,
            items=[
                ExtractedEmailItem(part_number="MS20470AD4-6", quantity=50, unit_price=0.12, condition_code="NE", lead_time_days=2, trace_documents=["CoC"]),
                ExtractedEmailItem(part_number="AN960-416", quantity=12, unit_price=0.08, condition_code="NE", lead_time_days=3, trace_documents=["FAA 8130-3"]),
            ],
        )
        service = SupplierEmailIngestionService()
        with patch("services.supplier_ingestion_service.extract_email_intelligence", return_value=extraction):
            result = service.ingest_email(
                "From: quotes@multi.example\nSubject: Two-line quote\n\nPart Number: MS20470AD4-6\nQuantity: 50\n$0.12\nPart Number: AN960-416\nQuantity: 12\n$0.08",
                message_id="multi-line-reliability",
            )

        self.assertTrue(result["success"], result)
        self.assertEqual({item["part_number"] for item in result["items"]}, {"MS20470AD4-6", "AN960-416"})
        offers = supplier_db.find_supplier_offers("AN960-416", quantity_needed=12)
        self.assertTrue(any(row["supplier_email"] == "quotes@multi.example" for row in offers))

    def test_agent_handoff_uses_configured_operations_path(self):
        import os
        from tempfile import TemporaryDirectory
        from services.agent_handoff_store import AgentHandoffStore

        with TemporaryDirectory() as directory:
            path = os.path.join(directory, "operations.db")
            store = AgentHandoffStore(path)
            handoff = store.save("RFQ-1", "Intake", "Sourcing", {"part_number": "060-1234-00"})
            self.assertEqual(store.list_for_rfq("RFQ-1")[0].handoff_id, handoff.handoff_id)


if __name__ == "__main__":
    unittest.main()
