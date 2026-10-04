import unittest

from agents.compliance_agent import ComplianceAgent


class TestComplianceAgent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = ComplianceAgent()

    async def test_verified_documentation_is_approved(self):
        response = await self.agent.execute({
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "supplier_approved": True,
            "certificate_type": "FAA 8130-3",
            "certificate_status": "valid",
            "expiration_date": "2099-12-31",
            "has_full_trace": True,
            "trace_documents": ["FAA-8130-3.pdf"],
            "requested_certificate_type": "FAA 8130-3",
        })

        self.assertTrue(response.success)
        self.assertEqual(response.data["compliance_status"], "APPROVED")
        self.assertEqual(response.data["issues_detected"], [])

    async def test_missing_verifiable_documents_requires_human_review(self):
        response = await self.agent.execute({
            "part_number": "PN-999",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "supplier_approved": True,
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        })

        self.assertTrue(response.success)
        self.assertEqual(response.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertIsNotNone(response.escalation_triggered)
        self.assertTrue(any("Incomplete traceability" in issue for issue in response.data["issues_detected"]))

    async def test_expired_certificate_is_rejected(self):
        response = await self.agent.execute({
            "part_number": "PN-002",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "supplier_approved": True,
            "certificate_type": "EASA Form 1",
            "certificate_status": "expired",
            "expiration_date": "2022-06-30",
            "has_full_trace": True,
            "trace_documents": ["EASA-Form-1.pdf"],
        })

        self.assertFalse(response.success)
        self.assertEqual(response.data["compliance_status"], "REJECTED")
        self.assertTrue(any("expired" in issue.lower() for issue in response.data["issues_detected"]))

    async def test_unapproved_supplier_is_rejected(self):
        response = await self.agent.execute({
            "part_number": "PN-003",
            "source": "Supplier",
            "supplier_name": "Blacklisted Co",
            "supplier_approved": False,
            "certificate_type": "FAA 8130-3",
            "certificate_status": "valid",
            "expiration_date": "2099-12-31",
            "has_full_trace": True,
            "trace_documents": ["FAA-8130-3.pdf"],
        })

        self.assertFalse(response.success)
        self.assertEqual(response.data["compliance_status"], "REJECTED")
        self.assertTrue(any("not approved" in issue.lower() for issue in response.data["issues_detected"]))

    async def test_requested_certificate_mismatch_requires_human_review(self):
        response = await self.agent.execute({
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "supplier_approved": True,
            "certificate_type": "CoC",
            "certificate_status": "valid",
            "expiration_date": "2099-12-31",
            "has_full_trace": True,
            "trace_documents": ["CoC.pdf"],
            "requested_certificate_type": "FAA 8130-3",
        })

        self.assertTrue(response.success)
        self.assertEqual(response.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")

    async def test_traceability_without_documents_requires_human_review(self):
        response = await self.agent.execute({
            "part_number": "060-1234-00",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "supplier_approved": True,
            "certificate_type": "FAA 8130-3",
            "certificate_status": "valid",
            "expiration_date": "2099-12-31",
            "has_full_trace": True,
            "trace_documents": [],
            "requested_certificate_type": "FAA 8130-3",
        })

        self.assertTrue(response.success)
        self.assertEqual(response.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertIsNotNone(response.escalation_triggered)


if __name__ == "__main__":
    unittest.main()
