import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.db_service import db_service
from services.operations_store import OperationsStore


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
            ("get", "/api/internal/purchase-orders"),
            ("get", "/api/internal/mailboxes/sales/inbox"),
            ("post", f"/api/rfqs/{self.customer_rfq.id}/process"),
        ]
        for method, path in checks:
            self.assertEqual(getattr(self.client, method)(path).status_code, 403, path)


class TestMailboxInboxProjection(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_ADMIN", "email": "admin@example.com"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_inbox_returns_message_summary_without_raw_mime_or_attachment_contents(self):
        message = {
            "mailbox": "sales",
            "message_id": "MSG-1",
            "internet_message_id": "<message@example.com>",
            "conversation_id": "CONV-1",
            "from": "buyer@example.com",
            "subject": "PN-100 availability",
            "date": "2026-09-28T10:00:00Z",
            "body": "Please confirm current availability.",
            "raw_mime": b"secret raw mime payload",
            "attachments": [{"filename": "po.pdf", "content_type": "application/pdf", "content": b"secret attachment bytes"}],
        }
        with patch("api.main.fetch_inbox_messages", return_value=[message]):
            response = self.client.get("/api/internal/mailboxes/sales/inbox")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["messages"][0]["body"], "Please confirm current availability.")
        self.assertEqual(payload["messages"][0]["attachments"], [{"filename": "po.pdf", "content_type": "application/pdf"}])
        self.assertNotIn("raw_mime", payload["messages"][0])
        self.assertNotIn("content", payload["messages"][0]["attachments"][0])


class TestPurchaseOrderReviewApi(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {"role": "ROLE_PURCHASING", "email": "purchasing@example.com"}
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_pending_purchase_order_queue_returns_operational_review_fields(self):
        pending = [{
            "id": "PO-REVIEW-1",
            "po_number": "CUST-PO-100",
            "customer_email": "buyer@example.com",
            "total_amount": 4200.0,
            "status": "Pending_PO_Review",
            "quote_id": "QTE-100",
            "rfq_id": "WT-100",
            "attachment_metadata": [{"attachment_id": "ATT-PO-1"}],
        }]
        with patch("api.main.operations_store.list_purchase_orders", return_value=pending) as list_orders:
            response = self.client.get("/api/internal/purchase-orders")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), pending)
        list_orders.assert_called_once_with(status="Pending_PO_Review")

    def test_po_approval_updates_the_operational_queue_status(self):
        quote = SimpleNamespace(rfq_id="WT-100")
        rfq = SimpleNamespace(id="WT-100", status="Pending_PO_Review")
        with (
            patch("api.main.db_service.get_quote", return_value=quote),
            patch("api.main.db_service.get_rfq", return_value=rfq),
            patch("api.main.orchestration_service.approve_purchase_order") as approve,
            patch("api.main.operations_store.update_purchase_order_status", return_value=True) as update_status,
        ):
            response = self.client.post(
                "/api/purchase-orders/QTE-100/approve",
                json={"operator_name": "Purchasing Operator", "comments": "Documents verified."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Purchase_Order_Received")
        approve.assert_called_once_with("WT-100", "Purchasing Operator", "Documents verified.")
        update_status.assert_called_once_with("QTE-100", "APPROVED")

    def test_purchase_order_queue_persists_and_removes_approved_rows(self):
        with TemporaryDirectory() as directory:
            store = OperationsStore(Path(directory) / "operations.db")
            connection = store._connect()
            try:
                connection.execute(
                    "INSERT INTO customers (id, company_name, email, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    ("CUS-1", "Buyer Company", "buyer@example.com", "2026-09-28T00:00:00Z", "2026-09-28T00:00:00Z"),
                )
                connection.execute(
                    "INSERT INTO rfqs (id, customer_id, quantity, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("WT-1", "CUS-1", 1, "Pending_PO_Review", "2026-09-28T00:00:00Z", "2026-09-28T00:00:00Z"),
                )
                connection.execute(
                    "INSERT INTO customer_quotes (id, rfq_id, quote_number, unit_price, quantity, total_price, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("QTE-1", "WT-1", "QUOTE-1", 1250.0, 1, 1250.0, "APPROVED", "2026-09-28T00:00:00Z", "2026-09-28T00:00:00Z"),
                )
                connection.commit()
            finally:
                connection.close()
            store.record_purchase_order(
                po_id="PO-1",
                po_number="CUST-1",
                customer_email="buyer@example.com",
                total_amount=1250.0,
                status="Pending_PO_Review",
                quote_id="QTE-1",
                rfq_id="WT-1",
                received_message_id=None,
                attachment_metadata=[{"attachment_id": "ATT-1"}],
            )

            pending = store.list_purchase_orders()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["attachment_metadata"], [{"attachment_id": "ATT-1"}])
            self.assertTrue(store.update_purchase_order_status("QTE-1", "APPROVED"))
            self.assertEqual(store.list_purchase_orders(), [])
            self.assertFalse(store.update_purchase_order_status("QTE-1", "APPROVED"))


if __name__ == "__main__":
    unittest.main()
