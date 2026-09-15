import tempfile
import unittest
from pathlib import Path

from services.relational_db import ensure_schema, seed_relational_mock_data
from services.role_queries import get_procurement_dashboard_data, get_sales_dashboard_data


class RoleQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "role_queries_test.db"
        ensure_schema(self.db_path)
        seed_relational_mock_data(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_sales_dashboard_filters_pipeline_statuses_and_returns_history(self) -> None:
        data = get_sales_dashboard_data(self.db_path)
        statuses = {row["status"] for row in data["rfqs"]}

        self.assertTrue({"PENDING_QUOTE", "PO_PENDING", "SOLVED"}.issuperset(statuses))
        self.assertGreaterEqual(len(data["rfqs"]), 1)
        self.assertGreaterEqual(len(data["client_history"]), 1)
        self.assertIn("records", data["client_history"][0])

    def test_procurement_dashboard_returns_supplier_inventory_and_pending_pos(self) -> None:
        data = get_procurement_dashboard_data(self.db_path)

        self.assertGreaterEqual(len(data["suppliers"]), 1)
        self.assertGreaterEqual(len(data["pending_purchase_orders"]), 1)
        self.assertIn("active_inventory_items", data["suppliers"][0])
        self.assertEqual(data["pending_purchase_orders"][0]["po_status"], "PENDING_PROCUREMENT")


if __name__ == "__main__":
    unittest.main()
