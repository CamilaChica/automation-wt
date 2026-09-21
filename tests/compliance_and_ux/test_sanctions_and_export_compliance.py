"""Export-control quality gates for aviation RFQs."""

import asyncio
import unittest

from agents.compliance_agent import ComplianceAgent
from agents.rfq_intake_agent import RFQIntakeAgent


class TestSanctionsAndExportCompliance(unittest.TestCase):
    def test_incomplete_trace_blocks_automatic_compliance_approval(self):
        result = asyncio.run(ComplianceAgent().execute({
            "part_number": "060-1234-00",
            "source": "Supplier",
            "supplier_name": "Approved Supplier",
            "certificate_type": "FAA 8130-3",
            "has_full_trace": False,
        }))

        self.assertEqual(result.data["compliance_status"], "HUMAN_REVIEW_REQUIRED")
        self.assertIsNotNone(result.escalation_triggered)

    def test_export_requirements_are_extracted_from_rfq_text(self):
        result = asyncio.run(RFQIntakeAgent().execute({
            "raw_text": (
                "Company: Global Airlines\nPart No: XYZ123\nQuantity: 1\n"
                "Condition: NE\nFAA 8130-3 required. End-user certificate required."
            )
        }))

        self.assertIn("FAA 8130-3", result.data["certification_requirements"])

    @unittest.skip("End-user certificate extraction and persistence are not implemented.")
    def test_euc_requirement_is_persisted_for_export_review(self):
        pass

    @unittest.skip("BIS/OFAC/ITAR denied-party screening service is not implemented.")
    def test_denied_entity_is_blocked_for_compliance_review(self):
        pass

    @unittest.skip("ECCN/ITAR part classification and EUC workflow are not implemented.")
    def test_dual_use_component_requires_euc_before_quote(self):
        pass


if __name__ == "__main__":
    unittest.main()
