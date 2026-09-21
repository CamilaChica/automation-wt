import unittest

from services.document_verification import (
    DocumentType,
    DocumentVerificationRequest,
    ExtractedCertificate,
    verify_certificate,
)


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


if __name__ == "__main__":
    unittest.main()
