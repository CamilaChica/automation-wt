import asyncio
import unittest
from agents.compliance_agent import ComplianceAgent

class TestComplianceAgent(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = ComplianceAgent()

    async def test_fully_compliant_part(self):
        """Part PN-001 is fully compliant and should be APPROVED."""
        inputs = {
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }
        response = await self.agent.execute(inputs)
        self.assertTrue(response.success)
        self.assertEqual(response.data["compliance_status"], "APPROVED")
        self.assertEqual(response.data["issues_detected"], [])

    async def test_missing_documentation(self):
        """No record for part number should trigger REJECTED and HUMAN_REVIEW_REQUIRED."""
        inputs = {
            "part_number": "PN-999",
            "source": "Supplier",
            "supplier_name": "Unknown",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }
        response = await self.agent.execute(inputs)
        self.assertFalse(response.success)
        self.assertIn(response.data["compliance_status"], ["REJECTED", "HUMAN_REVIEW_REQUIRED"])
        self.assertTrue(any("No documentation" in issue for issue in response.data["issues_detected"]))

    async def test_expired_documentation(self):
        """Part PN-002 has an expired certificate, should be REJECTED."""
        inputs = {
            "part_number": "PN-002",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "EASA Form 1",
            "has_full_trace": True,
        }
        response = await self.agent.execute(inputs)
        self.assertFalse(response.success)
        self.assertEqual(response.data["compliance_status"], "REJECTED")
        self.assertTrue(any("expired" in issue.lower() for issue in response.data["issues_detected"]))

    async def test_supplier_not_approved(self):
        """Part PN-003 has supplier not approved, should be REJECTED."""
        inputs = {
            "part_number": "PN-003",
            "source": "Supplier",
            "supplier_name": "Blacklisted Co",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": True,
        }
        response = await self.agent.execute(inputs)
        self.assertFalse(response.success)
        self.assertEqual(response.data["compliance_status"], "REJECTED")
        self.assertTrue(any("not approved" in issue.lower() for issue in response.data["issues_detected"]))

    async def test_part_number_mismatch(self):
        """Certificate type does not match the record for the part, should be REJECTED."""
        inputs = {
            "part_number": "PN-001",
            "source": "Supplier",
            "supplier_name": "AeroSupplies Inc",
            "certificate_type": "EASA Form 1",  # mismatch
            "has_full_trace": True,
        }
        response = await self.agent.execute(inputs)
        self.assertFalse(response.success)
        self.assertEqual(response.data["compliance_status"], "REJECTED")
        self.assertTrue(any("certificate type mismatch" in issue.lower() for issue in response.data["issues_detected"]))

if __name__ == "__main__":
    unittest.main()
