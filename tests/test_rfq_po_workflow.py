import unittest

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service


class TestRfqPoWorkflow(unittest.TestCase):
    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.inventory.clear()
        db_service.seed_mock_data()
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.com"}

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_catalog_search_filters_case_insensitively_by_condition(self):
        response = TestClient(app).get("/api/catalog/search", params={"query": "060-1234", "condition": "ne"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json())
        self.assertTrue(all(item["part_number"].lower().find("060-1234") >= 0 for item in response.json()))
        self.assertTrue(all(item["condition_code"] == "NE" for item in response.json()))

    def test_purchase_order_requires_three_attachment_ids(self):
        rfq = db_service.create_rfq("Buyer", "buyer@example.com", "P/N 060-1234-00 qty 1")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        response = TestClient(app).post(
            "/api/purchase-orders",
            json={"quote_id": quote.id, "po_number": "PO-1001", "customer_email": "buyer@example.com", "attachment_ids": ["ATT-1"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Three signed documents", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
