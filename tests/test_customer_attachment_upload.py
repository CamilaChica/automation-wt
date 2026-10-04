import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app, get_async_db
from services.attachment_service import AttachmentService


class TestCustomerAttachmentUpload(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_CUSTOMER",
            "email": "buyer@example.com",
        }
        app.dependency_overrides[get_async_db] = lambda: None

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_upload_returns_attachment_id_for_authenticated_customer(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("api.main.attachment_service", AttachmentService(directory)):
                response = TestClient(app).post(
                    "/api/attachments",
                    files={"file": ("euc.pdf", b"%PDF-1.4 test", "application/pdf")},
                )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["attachment_id"].startswith("ATT-"))
        self.assertEqual(payload["status"], "ACCEPTED")
        self.assertNotIn("stored_path", payload)
        self.assertNotIn("sha256", payload)

    def test_rfq_intake_passes_uploaded_parts_list_contents_to_pipeline(self):
        rfq = SimpleNamespace(id="RFQ-ATTACH1", status="Intake")
        csv_content = b"Part Number,Quantity,Condition\nPN-ABC-123,2,OH\n"
        with tempfile.TemporaryDirectory() as directory:
            attachments = AttachmentService(directory)
            record = attachments.validate_and_store(
                "parts.csv",
                "text/csv",
                io.BytesIO(csv_content),
            )
            with patch("api.main.attachment_service", attachments), patch(
                "api.main.db_service.create_rfq", return_value=rfq
            ) as create_rfq, patch(
                "api.main.operations_store.record_automation_event",
            ) as queue_event:
                response = TestClient(app).post(
                    "/api/rfqs/intake",
                    json={
                        "raw_text": "Customer parts list attached (parts.csv).",
                        "customer_name": "Test Buyer",
                        "attachment_ids": [record.attachment_id],
                    },
                )

        self.assertEqual(response.status_code, 200)
        submitted_text = create_rfq.call_args.kwargs["raw_text"]
        self.assertIn("PN-ABC-123", submitted_text)
        self.assertIn("PN-ABC-123,2,OH", submitted_text)
        self.assertEqual(response.json()["status"], "Processing_Queued")
        self.assertEqual(queue_event.call_args.kwargs["event_type"], "process_new_rfq")
        self.assertEqual(queue_event.call_args.kwargs["entity_id"], "RFQ-ATTACH1")

    def test_rfq_intake_rejects_missing_attachment_instead_of_ignoring_it(self):
        with patch("api.main.db_service.create_rfq") as create_rfq:
            response = TestClient(app).post(
                "/api/rfqs/intake",
                json={
                    "raw_text": "Customer parts list attached.",
                    "customer_name": "Test Buyer",
                    "attachment_ids": ["ATT-0000000000000001"],
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("upload it again", response.json()["detail"])
        create_rfq.assert_not_called()


if __name__ == "__main__":
    unittest.main()
