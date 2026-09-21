import io
import tempfile
import unittest
from pathlib import Path

from services.attachment_service import AttachmentService
from services.agent_handoff_store import AgentHandoffStore


class TestAttachmentAndHandoff(unittest.TestCase):
    def test_valid_pdf_is_stored_and_hashed(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            record = AttachmentService(directory).validate_and_store("cert.pdf", "application/pdf", io.BytesIO(b"%PDF-1.4"))
            self.assertEqual(record.status, "ACCEPTED")
            self.assertTrue(Path(record.stored_path).exists())
            self.assertEqual(len(record.sha256), 64)

    def test_unsupported_attachment_is_rejected(self):
        record = AttachmentService().validate_and_store("payload.exe", "application/octet-stream", io.BytesIO(b"bad"))
        self.assertEqual(record.status, "REJECTED")

    def test_agent_handoff_survives_store_reload(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            path = Path(directory) / "operations.db"
            AgentHandoffStore(path).save("RFQ-1", "RFQAgent", "PricingAgent", {"part_number": "XYZ123", "quantity": 2})
            rows = AgentHandoffStore(path).list_for_rfq("RFQ-1")
        self.assertEqual(rows[0].payload["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
