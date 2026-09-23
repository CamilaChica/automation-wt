import unittest

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service
from services.supplier_database import supplier_db


class TestCatalogSupplierSearch(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_CUSTOMER", "email": "buyer@example.com"}
        supplier_db.save_supplier_offer(
            supplier_name="Quoted Supplier",
            supplier_email="quotes@example.com",
            part_number="822-1287-121",
            quantity_available=4,
            unit_cost=2500.0,
            certificate_type="FAA 8130-3",
            lead_time_days=5,
            approval_status="Approved",
            condition_code="OH",
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_supplier_quoted_part_is_visible_to_customer_search(self):
        response = TestClient(app).get("/api/catalog/search", params={"query": "822-1287-121"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["part_number"], "822-1287-121")
        self.assertEqual(response.json()[0]["condition_code"], "OH")

    def test_empty_query_returns_empty_search_state(self):
        response = TestClient(app).get("/api/catalog/search", params={"query": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


if __name__ == "__main__":
    unittest.main()
