import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.document_verification import (
    DocumentType,
    DocumentVerificationRequest,
    ExtractedCertificate,
    verify_certificate,
    compare_documents,
)
from tests.test_document_parser import certificate_pdf


class TestDocumentVerification(unittest.TestCase):
    def _request(self, **overrides):
        extracted = {
            "document_type": DocumentType.FAA_8130_3,
            "part_number": "060-1234-00",
            "serial_number": "SN-1",
            "condition_code": "NE",
            "confidence": 0.98,
        }
        extracted.update(overrides)
        return DocumentVerificationRequest(
            expected_part_number="060-1234-00",
            expected_serial_number="SN-1",
            expected_condition_code="NE",
            extracted=ExtractedCertificate(**extracted),
        )

    def test_matching_certificate_is_verified(self):
        result = verify_certificate(self._request())

        self.assertEqual(result.status, "VERIFIED")
        self.assertFalse(result.requires_human_review)

    def test_part_mismatch_requires_review(self):
        result = verify_certificate(self._request(part_number="999-0000-00"))

        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertTrue(result.requires_human_review)
        self.assertIn("Part number", result.discrepancies[0])

    def test_low_confidence_requires_review(self):
        result = verify_certificate(self._request(confidence=0.4))

        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertTrue(any("confidence" in item.lower() for item in result.discrepancies))

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self._request(unexpected_field="blocked")

    def test_real_certificates_compare_serial_disagreement(self):
        report = compare_documents([
            {"filename": "cert-a.pdf", "content": certificate_pdf(serial_number="SN-1")},
            {"filename": "cert-b.pdf", "content": certificate_pdf(serial_number="SN-2")},
        ], expected_part_number="PN-123")
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertEqual(report["authenticity"], "NOT_VERIFIED")
        self.assertTrue(any("serial_number" in value for value in report["discrepancies"]))

    def test_part_mismatch_and_missing_serial_are_not_verified(self):
        report = compare_documents([
            {"filename": "cert.pdf", "content": certificate_pdf()},
        ], expected_part_number="PN-999", expected_serial_number="SN-2")
        self.assertTrue(report["requires_human_review"])
        self.assertTrue(any("part_number" in value for value in report["discrepancies"]))
        self.assertTrue(any("serial_number" in value for value in report["discrepancies"]))

    def test_matching_document_preserves_evidence_not_authenticity_claim(self):
        report = compare_documents([
            {"filename": "cert.pdf", "content": certificate_pdf()},
        ], expected_part_number="PN-123", expected_serial_number="SN-1")
        self.assertEqual(report["status"], "FIELDS_CONSISTENT")
        self.assertEqual(report["authenticity"], "NOT_VERIFIED")
        self.assertEqual(report["documents"][0]["evidence"]["part_number"], "Part Number: PN-123")

    def test_supplier_ingestion_holds_unreadable_certificate_before_offer_persistence(self):
        from services.supplier_ingestion_service import SupplierEmailIngestionService

        service = SupplierEmailIngestionService.__new__(SupplierEmailIngestionService)
        with patch("services.supplier_ingestion_service.operations_store") as store:
            result = service.ingest_email(
                "From: supplier@example.invalid\nPart Number: PN-123",
                message_id="supplier-cert-test",
                attachments=[{"filename": "certificate.pdf", "content": b"corrupt"}],
            )
        self.assertEqual(result["status"], "Pending_Human_Review")
        store.enqueue_operator_review.assert_called_once()
        self.assertEqual(store.record_automation_event.call_args.kwargs["event_type"], "supplier_document_comparison")

    def test_async_supplier_ingestion_holds_conflicting_certificate_documents(self):
        from services.supplier_ingestion_service import SupplierEmailIngestionService

        service = SupplierEmailIngestionService.__new__(SupplierEmailIngestionService)
        records = SimpleNamespace(
            record_automation_event=AsyncMock(),
            enqueue_operator_review=AsyncMock(return_value="review-document-test"),
        )
        result = asyncio.run(service.ingest_email_async(
            "From: supplier@example.invalid\nPart Number: PN-123",
            SimpleNamespace(records=records), message_id="supplier-serial-test",
            attachments=[
                {"filename": "certificate-a.pdf", "content": certificate_pdf(serial_number="SN-1")},
                {"filename": "certificate-b.pdf", "content": certificate_pdf(serial_number="SN-2")},
            ],
        ))
        self.assertEqual(result["status"], "Pending_Human_Review")
        records.enqueue_operator_review.assert_awaited_once()
        self.assertIn("serial_number", records.enqueue_operator_review.call_args.kwargs["hold_flags"][0])


if __name__ == "__main__":
    unittest.main()
