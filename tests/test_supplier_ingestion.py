import json
import tempfile
import unittest
from pathlib import Path

from services.db_service import db_service
from services.relational_db import db_connection, ensure_schema
from services.supplier_ingestion import ingest_supplier_quote_email


class StubRouter:
    def parse_rfq(self, text: str) -> dict:
        del text
        return {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "fallback_used": False,
            "result": {
                "supplier_email": "quotes@newvendor.com",
                "part_number": "ab-1000",
                "condition": "NE",
                "unit_cost": 123.45,
                "quantity_available": 7,
                "lead_time_days": 4,
                "certificate_type": "FAA 8130-3",
            },
        }


class SupplierIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "supplier_ingestion.db"
        ensure_schema(self.db_path)
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.inventory.clear()
        db_service.suppliers.clear()
        db_service.supplier_quotes.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.seed_mock_data()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ingestion_creates_supplier_and_upserts_inventory(self) -> None:
        result = ingest_supplier_quote_email(
            source_email_id="msg-1",
            raw_quote_text="raw message payload",
            ai_router=StubRouter(),
            database=db_service,
            db_path=self.db_path,
        )

        supplier = db_service.get_supplier_by_email("quotes@newvendor.com")
        self.assertIsNotNone(supplier)
        inventory_match = [item for item in db_service.inventory.values() if item.part_number == "AB-1000" and item.condition_code == "NE"]
        self.assertEqual(len(inventory_match), 1)
        self.assertEqual(inventory_match[0].quantity_available, 7)
        self.assertAlmostEqual(inventory_match[0].unit_cost, 123.45)
        self.assertEqual(result["provider"], "gemini")

        logs = db_service.get_audit_logs("INGEST-msg-1")
        self.assertEqual(len(logs), 1)
        payload = json.loads(logs[0].payload_json)
        self.assertEqual(payload["source_email_id"], "msg-1")
        self.assertEqual(payload["supplier_id"], supplier.id)
        with db_connection(self.db_path) as connection:
            audit_count = connection.execute("SELECT COUNT(*) AS count FROM agent_audit_logs").fetchone()["count"]
        self.assertEqual(audit_count, 1)

    def test_ingestion_updates_existing_part_condition(self) -> None:
        first_router = StubRouter()
        second_router = StubRouter()
        second_router.parse_rfq = lambda _text: {
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "fallback_used": False,
            "result": {
                "supplier_email": "quotes@newvendor.com",
                "part_number": "AB-1000",
                "condition": "NE",
                "unit_cost": 99.0,
                "quantity_available": 10,
                "lead_time_days": 2,
                "certificate_type": "EASA Form 1",
            },
        }

        ingest_supplier_quote_email(
            source_email_id="msg-2",
            raw_quote_text="raw message payload",
            ai_router=first_router,
            database=db_service,
            db_path=self.db_path,
        )
        ingest_supplier_quote_email(
            source_email_id="msg-3",
            raw_quote_text="raw message payload update",
            ai_router=second_router,
            database=db_service,
            db_path=self.db_path,
        )

        inventory_match = [item for item in db_service.inventory.values() if item.part_number == "AB-1000" and item.condition_code == "NE"]
        self.assertEqual(len(inventory_match), 1)
        self.assertEqual(inventory_match[0].quantity_available, 10)
        self.assertAlmostEqual(inventory_match[0].unit_cost, 99.0)
        self.assertEqual(inventory_match[0].certificate_type, "EASA Form 1")


if __name__ == "__main__":
    unittest.main()
