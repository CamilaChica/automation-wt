import unittest

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service
from services.procurement_service import procurement_service
from services.sales_automation_service import sales_automation_service


class APIAutomationEndpointsTests(unittest.TestCase):
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

        procurement_service.email_sender = lambda *args, **kwargs: None
        sales_automation_service.email_sender = lambda *args, **kwargs: None

        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_ADMIN",
            "email": "camila@wingedtycoons.com",
        }
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_ingest_supplier_quote_endpoint(self) -> None:
        response = self.client.post(
            "/api/internal/purchasing/ingest-quote",
            json={
                "source_email_id": "api-msg-1",
                "raw_quote_text": (
                    "From: quotes@skybridgeparts.com\n"
                    "Part Number: 777-ABC-11\n"
                    "Condition: NE\n"
                    "Price: 1999.50\n"
                    "Quantity: 6\n"
                    "Lead Time: 7\n"
                    "Certificate: FAA 8130-3\n"
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["result"]["parsed"]["part_number"], "777-ABC-11")

    def test_procurement_pending_endpoint(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need parts")
        item = db_service.add_rfq_item(rfq.id, "060-1234-00", 5, condition="NE")
        item.resolved_part_number = "060-1234-00"
        trigger = self.client.post(f"/api/internal/procurement/trigger/{rfq.id}")
        self.assertEqual(trigger.status_code, 200)
        pending = self.client.get("/api/internal/procurement/pending")
        self.assertEqual(pending.status_code, 200)
        self.assertGreaterEqual(len(pending.json()["items"]), 1)

    def test_sales_quote_endpoint(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need part")
        item = db_service.add_rfq_item(rfq.id, "060-1234-00", 1, condition="NE")
        item.resolved_part_number = "060-1234-00"
        response = self.client.post(f"/api/internal/sales/quote/{rfq.id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("quote_id", body)
        self.assertIn("approval_required", body)

    def test_sales_status_endpoint(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need part")
        response = self.client.post(
            f"/api/internal/sales/rfq/{rfq.id}/status",
            json={"status": "Solved"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Solved")

    def test_agentic_run_endpoint(self) -> None:
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need part")
        item = db_service.add_rfq_item(rfq.id, "060-1234-00", 3, condition="NE")
        item.resolved_part_number = "060-1234-00"
        response = self.client.post(
            "/api/internal/sales/agentic/run",
            json={"rfq_id": rfq.id},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["rfq_id"], rfq.id)
        self.assertIn("quote_outcome", payload)

    def test_role_guard_blocks_customer_from_procurement_trigger(self) -> None:
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_CUSTOMER",
            "email": "customer@example.com",
        }
        rfq = db_service.create_rfq("Delta MRO Services", "procurement@deltamro.com", "Need parts")
        response = self.client.post(f"/api/internal/procurement/trigger/{rfq.id}")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
