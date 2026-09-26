import unittest
from unittest.mock import patch

from services.email_intelligence import EmailIntelligenceExtraction, ExtractedEmailItem
from schemas.extraction import ExtractedField
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
                ExtractedEmailItem(
                    part_number=ExtractedField(value="MS20470AD4-6", source_snippet="Part Number: MS20470AD4-6"),
                    quantity=ExtractedField(value="50", source_snippet="Quantity: 50"),
                    condition_code=ExtractedField(value="NE", source_snippet="Condition: NE"),
                    target_price=ExtractedField(value="0.12", source_snippet="$0.12"),
                    lead_time_days=ExtractedField(value="2", source_snippet="Lead time 2"),
                    unit_of_measure=ExtractedField(value="EA", source_snippet="Quantity: 50"),
                    currency=ExtractedField(value="USD", source_snippet="$0.12"),
                    trace_documents=["CoC"],
                ),
                ExtractedEmailItem(
                    part_number=ExtractedField(value="AN960-416", source_snippet="Part Number: AN960-416"),
                    quantity=ExtractedField(value="12", source_snippet="Quantity: 12"),
                    condition_code=ExtractedField(value="NE", source_snippet="Condition: NE"),
                    target_price=ExtractedField(value="0.08", source_snippet="$0.08"),
                    lead_time_days=ExtractedField(value="3", source_snippet="Lead time 3"),
                    unit_of_measure=ExtractedField(value="EA", source_snippet="Quantity: 12"),
                    currency=ExtractedField(value="USD", source_snippet="$0.08"),
                    trace_documents=["FAA 8130-3"],
                ),
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
