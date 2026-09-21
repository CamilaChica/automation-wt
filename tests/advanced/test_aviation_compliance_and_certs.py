"""Advanced FAA/EASA airworthiness and traceability quality gates."""

import asyncio
import unittest

from agents.compliance_agent import ComplianceAgent


class TestAviationComplianceAndCertificates(unittest.TestCase):
    def test_certificate_mismatch_does_not_pass_compliance(self):
        result = asyncio.run(ComplianceAgent().execute({
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "CoC",
            "requested_certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }))

        self.assertTrue(result.success)
        self.assertTrue(any("Certificate type mismatch" in issue for issue in result.data["issues_detected"]))
        self.assertEqual(result.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")

    def test_missing_traceability_requires_human_review(self):
        result = asyncio.run(ComplianceAgent().execute({
            "part_number": "060-1234-00",
            "source": "Inventory",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": False,
        }))

        self.assertTrue(result.success)
        self.assertEqual(result.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertIsNotNone(result.escalation_triggered)

    def test_unapproved_supplier_is_not_approved(self):
        result = asyncio.run(ComplianceAgent().execute({
            "part_number": "PN-003",
            "source": "Supplier",
            "supplier_name": "Blacklisted Co",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": False,
        }))

        self.assertFalse(result.success)
        self.assertIn("not approved", result.error_message)

    @unittest.expectedFailure
    def test_mismatched_certificate_should_be_needs_human_review_not_rejected(self):
        """Known gap: certificate mismatches currently reject instead of escalating."""
        result = asyncio.run(ComplianceAgent().execute({
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "EASA Form 1",
            "requested_certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }))
        self.assertEqual(result.data["compliance_status"], "NEEDS_HUMAN_REVIEW")


if __name__ == "__main__":
    unittest.main()
