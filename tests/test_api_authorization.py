import unittest

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service


class TestCustomerDataIsolation(unittest.TestCase):
    customer = {"role": "ROLE_CUSTOMER", "email": "customer@example.com"}

    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.seed_mock_data()
        self.customer_rfq = db_service.create_rfq(
            "Customer Example", "customer@example.com", "Need part 060-1234-00"
        )
        customer_item = db_service.add_rfq_item(self.customer_rfq.id, "060-1234-00", 1)
        quote = db_service.create_quote(self.customer_rfq.id, 1250.0, 25.0, 1275.0)
        db_service.add_quote_item(
            quote.id, customer_item.id, "060-1234-00", 1, "Inventory", 1000.0,
            1250.0, 20.0, "FAA 8130-3", "Pass"
        )
        db_service.add_audit_log(self.customer_rfq.id, "PricingAgent", "price", "Internal pricing detail")
        self.other_rfq = db_service.create_rfq("Other Customer", "other@example.com", "Need another part")
        app.dependency_overrides[current_user] = lambda: self.customer
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_customer_sees_only_own_safe_quote_data(self):
        response = self.client.get("/api/rfqs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [self.customer_rfq.id])

        response = self.client.get(f"/api/rfqs/{self.customer_rfq.id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("logs", payload)
        self.assertNotIn("unit_cost", payload["quote_details"]["items"][0])
        self.assertNotIn("margin_percent", payload["quote_details"]["items"][0])

        self.assertEqual(self.client.get(f"/api/rfqs/{self.other_rfq.id}").status_code, 403)

    def test_customer_is_denied_internal_endpoints(self):
        checks = [
            ("get", "/api/inventory"),
            ("get", "/api/suppliers"),
            ("get", "/api/internal/mailboxes/sales/inbox"),
            ("post", f"/api/rfqs/{self.customer_rfq.id}/process"),
        ]
        for method, path in checks:
            self.assertEqual(getattr(self.client, method)(path).status_code, 403, path)


if __name__ == "__main__":
    unittest.main()
