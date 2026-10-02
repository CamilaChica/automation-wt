import unittest
from unittest.mock import patch

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
        quote.status = "Sent"
        self.customer_quote = quote
        db_service.add_quote_item(
            quote.id, customer_item.id, "060-1234-00", 1, "Inventory", 1000.0,
            1250.0, 20.0, "FAA 8130-3", "Pass"
        )
        db_service.add_audit_log(self.customer_rfq.id, "PricingAgent", "price", "Internal pricing detail")
        self.other_rfq = db_service.create_rfq("Other Customer", "other@example.com", "Need another part")
        self.other_quote = db_service.create_quote(self.other_rfq.id, 500.0, 0.0, 500.0)
        self.other_quote.status = "Sent"
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
        quote_response = self.client.get(f"/api/quotes/{self.customer_quote.id}")
        self.assertEqual(quote_response.status_code, 200)
        quote_payload = quote_response.json()
        self.assertEqual(quote_payload["quote"]["rfq_id"], self.customer_rfq.id)
        self.assertEqual(quote_payload["rfq_status"], self.customer_rfq.status)
        self.assertNotIn("unit_cost", quote_payload["items"][0])
        self.assertNotIn("margin_percent", quote_payload["items"][0])
        self.assertEqual(
            self.client.get(f"/api/quotes/{self.other_quote.id}").status_code, 403
        )

    def test_customer_cannot_view_or_accept_unsent_quotes(self):
        quote = db_service.create_quote(self.customer_rfq.id, 300.0, 0.0, 300.0)
        self.assertEqual(self.client.get(f"/api/quotes/{quote.id}").status_code, 404)
        response = self.client.post(
            "/api/purchase-orders",
            json={
                "quote_id": quote.id,
                "po_number": "PO-UNSENT",
                "attachment_ids": ["ATT-1", "ATT-2", "ATT-3"],
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_customer_cannot_submit_po_for_another_customer_quote(self):
        response = self.client.post(
            "/api/purchase-orders",
            json={
                "quote_id": self.other_quote.id,
                "po_number": "PO-OTHER",
                "customer_email": self.customer["email"],
                "attachment_ids": ["ATT-1", "ATT-2", "ATT-3"],
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_customer_is_denied_internal_endpoints(self):
        checks = [
            ("get", "/api/inventory"),
            ("get", "/api/suppliers"),
            ("get", "/api/internal/mailboxes/sales/inbox"),
            ("post", f"/api/rfqs/{self.customer_rfq.id}/process"),
            ("get", "/api/attachments/ATT-0000000000000001"),
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


class TestFailedIntakeReset(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_ADMIN", "email": "operator@example.test"
        }
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_reset_requires_failed_state_and_audits_reason_without_processing(self):
        from types import SimpleNamespace

        failed_rfq = SimpleNamespace(id="RFQ-RESET", status="Intake_Failed")
        with (
            patch("api.main.db_service.get_rfq", return_value=failed_rfq),
            patch("api.main.db_service.update_rfq_status", return_value=failed_rfq) as update_status,
            patch("api.main.db_service.add_audit_log") as add_audit,
            patch("api.main.orchestration_service.process_rfq_pipeline") as process,
        ):
            response = self.client.post(
                "/api/internal/rfqs/RFQ-RESET/reset-intake",
                json={"reason": "Verified source document"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Intake")
        update_status.assert_called_once_with("RFQ-RESET", "Intake")
        add_audit.assert_called_once_with(
            "RFQ-RESET", "AutomationControl", "intake_reset",
            "Failed intake reset to Intake by operator@example.test. Reason: Verified source document",
            "WARNING",
        )
        process.assert_not_called()

    def test_reset_rejects_nonfailed_rfq_and_blank_reason(self):
        from types import SimpleNamespace

        with patch("api.main.db_service.get_rfq", return_value=SimpleNamespace(status="NEEDS_HUMAN_REVIEW")):
            response = self.client.post(
                "/api/internal/rfqs/RFQ-RESET/reset-intake", json={"reason": "Review"}
            )
        self.assertEqual(response.status_code, 409)

        with patch("api.main.db_service.get_rfq", return_value=SimpleNamespace(status="Intake_Failed")):
            response = self.client.post(
                "/api/internal/rfqs/RFQ-RESET/reset-intake", json={"reason": "   "}
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
