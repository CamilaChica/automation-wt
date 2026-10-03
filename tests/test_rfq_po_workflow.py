import io
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.attachment_service import AttachmentService
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

    def test_purchase_order_requires_po_attachment(self):
        rfq = db_service.create_rfq("Buyer", "buyer@example.com", "P/N 060-1234-00 qty 1")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        quote.status = "Sent"
        response = TestClient(app).post(
            "/api/purchase-orders",
            json={"quote_id": quote.id, "po_number": "PO-1001", "customer_email": "buyer@example.com", "attachment_ids": []},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("purchase order document", response.json()["detail"])

    def test_duplicate_purchase_order_does_not_send_second_notification(self):
        rfq = db_service.create_rfq("Buyer", "buyer@example.com", "P/N 060-1234-00 qty 1")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        quote.status = "Sent"
        with tempfile.TemporaryDirectory() as directory:
            attachments = AttachmentService(directory)
            attachment_ids = [
                attachments.validate_and_store(
                    f"document-{index}.pdf",
                    "application/pdf",
                    io.BytesIO(f"%PDF-1.4 document {index}".encode()),
                ).attachment_id
                for index in range(3)
            ]
            with patch("api.main.attachment_service", attachments), patch(
                "api.main.operations_store.record_purchase_order",
                return_value={"id": "PO-ALREADY-RECORDED", "status": "Pending_PO_Review"},
            ), patch("api.main.communication_service.validate_purchase_order_metadata"), patch(
                "api.main.communication_service.notify_purchase_order"
            ) as notify:
                response = TestClient(app).post(
                    "/api/purchase-orders",
                    json={
                        "quote_id": quote.id,
                        "po_number": "PO-1001",
                        "customer_email": "buyer@example.com",
                        "attachment_ids": attachment_ids,
                    },
                )

        self.assertEqual(response.status_code, 409)
        notify.assert_not_called()

    def test_purchase_order_rejects_unuploaded_or_invalid_pdfs(self):
        rfq = db_service.create_rfq("Buyer", "buyer@example.com", "P/N 060-1234-00 qty 1")
        quote = db_service.create_quote(rfq.id, 100.0, 0.0, 100.0)
        quote.status = "Sent"
        response = TestClient(app).post(
            "/api/purchase-orders",
            json={
                "quote_id": quote.id,
                "po_number": "PO-1002",
                "attachment_ids": [
                    "ATT-0000000000000001",
                    "ATT-0000000000000002",
                    "ATT-0000000000000003",
                ],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("accepted documents", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
