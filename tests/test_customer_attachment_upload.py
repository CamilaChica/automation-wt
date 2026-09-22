import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app
from services.attachment_service import AttachmentService


class TestCustomerAttachmentUpload(unittest.TestCase):
    def test_upload_returns_attachment_id_for_authenticated_customer(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_CUSTOMER",
            "email": "buyer@example.com",
        }
        try:
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
        finally:
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
