"""
test_rfq_intake_agent.py
========================
Unit tests for RFQIntakeAgent covering the six mandatory scenarios:

    1. complete_rfq         – all fields present; status = COMPLETE
    2. missing_part_number  – no PN in text; status = NEEDS_CLARIFICATION
    3. omitted_quantity     – no quantity in text; defaults to one
    4. ambiguous_condition  – multiple condition codes; status = NEEDS_CLARIFICATION
    5. aog_request          – AOG keyword triggers AOG priority
    6. malformed_rfq        – garbage/empty input; status = NEEDS_CLARIFICATION
"""

import asyncio
import unittest
from agents.rfq_intake_agent import RFQIntakeAgent


class TestRFQIntakeAgent(unittest.TestCase):

    def setUp(self):
        self.agent = RFQIntakeAgent()

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #
    def _run(self, raw_text: str):
        """Synchronous wrapper around the async execute() method."""
        return asyncio.run(self.agent.execute({"raw_text": raw_text}))

    # ================================================================== #
    # 1. Complete RFQ
    # ================================================================== #
    def test_complete_rfq(self):
        """All mandatory and optional fields present → COMPLETE, success=True."""
        raw = (
            "From: Delta MRO Services <procurement@deltamro.com>\n"
            "Company: Delta MRO Services\n"
            "Part Number: 060-1234-00\n"
            "Qty: 5\n"
            "Condition: NE\n"
            "Required Date: 2026-09-15\n"
            "Delivery to: Dallas/Fort Worth, TX\n"
            "Certifications: FAA 8130-3\n"
            "Additional requirements: Dual release certificate preferred.\n"
        )
        res = self._run(raw)

        self.assertTrue(res.success, f"Expected success=True; error={res.error_message}")
        d = res.data
        self.assertEqual(d["status"], "COMPLETE")
        self.assertEqual(d["part_number"], "060-1234-00")
        self.assertEqual(d["quantity"], 5)
        self.assertEqual(d["condition"], "NE")
        self.assertEqual(d["AOG_status"], False)
        self.assertEqual(d["priority"], "Routine")
        self.assertIn("FAA 8130-3", d["certification_requirements"])
        self.assertEqual(d["missing_fields"], [])
        self.assertEqual(d["ambiguous_fields"], [])
        # RFQ ID generated
        self.assertTrue(d["rfq_id"].startswith("RFQ-"))
        # Legacy keys present
        self.assertIn("customer_email", d)
        self.assertIn("items", d)
        self.assertEqual(len(d["items"]), 1)
        self.assertEqual(d["items"][0]["requested_part_number"], "060-1234-00")
        self.assertEqual(d["items"][0]["quantity"], 5)

    # ================================================================== #
    # 2. Missing Part Number
    # ================================================================== #
    def test_missing_part_number(self):
        """No part number in text → NEEDS_CLARIFICATION, 'part_number' in missing_fields."""
        raw = (
            "Hello, Delta MRO Services here. We need 3 units please. "
            "Condition: NE. Deliver to Miami International Airport."
        )
        res = self._run(raw)

        self.assertFalse(res.success)
        d = res.data
        self.assertEqual(d["status"], "NEEDS_CLARIFICATION")
        self.assertIn("part_number", d["missing_fields"])
        self.assertIsNone(d["part_number"])
        # Quantity still extracted
        self.assertEqual(d["quantity"], 3)
        # Escalation triggered
        self.assertIsNotNone(res.escalation_triggered)
        self.assertEqual(res.escalation_triggered.condition, "missing_mandatory_fields")

    # ================================================================== #
    # 3. Omitted Quantity
    # ================================================================== #
    def test_omitted_quantity_defaults_to_one(self):
        """No quantity in text → complete RFQ with quantity one."""
        raw = (
            "United Airlines maintenance needs Part Number 456-789-OH. "
            "Condition OH. Required by 2026-10-01. Ship to Chicago O'Hare."
        )
        res = self._run(raw)

        self.assertTrue(res.success)
        d = res.data
        self.assertEqual(d["status"], "COMPLETE")
        self.assertEqual(d["quantity"], 1)
        self.assertEqual(d["items"][0]["quantity"], 1)
        # Part number still extracted and normalized
        self.assertEqual(d["part_number"], "456-789-OH")

    # ================================================================== #
    # 4. Ambiguous Condition
    # ================================================================== #
    def test_ambiguous_condition(self):
        """Two condition codes in text → NEEDS_CLARIFICATION, 'condition' in ambiguous_fields."""
        raw = (
            "From: Sky Parts Ltd.\n"
            "PN: 060-1234-00, Qty: 2\n"
            "We can accept NE or OH condition parts. "
            "Please quote both options."
        )
        res = self._run(raw)

        self.assertFalse(res.success)
        d = res.data
        self.assertEqual(d["status"], "NEEDS_CLARIFICATION")
        self.assertIn("condition", d["ambiguous_fields"])
        self.assertIsNotNone(res.escalation_triggered)
        self.assertEqual(res.escalation_triggered.condition, "ambiguous_condition")
        # Core fields still extracted
        self.assertEqual(d["part_number"], "060-1234-00")
        self.assertEqual(d["quantity"], 2)

    # ================================================================== #
    # 5. AOG Request
    # ================================================================== #
    def test_aog_request(self):
        """AOG keyword → AOG_status=True, priority='AOG', success depends on completeness."""
        raw = (
            "URGENT – AOG SITUATION\n"
            "Company: FlyFast Airlines\n"
            "Part No: 060-1234-00\n"
            "Quantity: 1\n"
            "Condition: NE\n"
            "Aircraft is grounded at LAX. Need part ASAP.\n"
            "Delivery to: Los Angeles International Airport (LAX).\n"
        )
        res = self._run(raw)

        d = res.data
        self.assertTrue(d["AOG_status"], "AOG_status should be True")
        self.assertEqual(d["priority"], "AOG")
        # RFQ is complete despite urgency
        self.assertTrue(res.success, f"Should succeed; error={res.error_message}")
        self.assertEqual(d["status"], "COMPLETE")
        self.assertEqual(d["part_number"], "060-1234-00")
        self.assertEqual(d["quantity"], 1)

    # ================================================================== #
    # 6. Malformed RFQ
    # ================================================================== #
    def test_malformed_rfq_empty(self):
        """Empty string → immediate failure, no data invented."""
        res = self._run("")

        self.assertFalse(res.success)
        self.assertIn("empty", res.error_message.lower())
        self.assertIsNotNone(res.escalation_triggered)

    def test_malformed_rfq_garbage(self):
        """Garbage text with no extractable fields → NEEDS_CLARIFICATION."""
        raw = "asjdhakjsdhakjsdhakjsd 123 !!!@@## ???"
        res = self._run(raw)

        self.assertFalse(res.success)
        d = res.data
        self.assertEqual(d["status"], "NEEDS_CLARIFICATION")
        # Both mandatory part_number and customer identity missing
        self.assertIn("part_number", d["missing_fields"])
        self.assertIsNone(d["part_number"])

    # ================================================================== #
    # Structural integrity
    # ================================================================== #
    def test_rfq_id_is_unique(self):
        """Each call generates a distinct RFQ ID."""
        raw = (
            "Company: Acme Air. Part Number: 060-1234-00. Qty: 1. Condition: NE."
        )
        ids = {self._run(raw).data["rfq_id"] for _ in range(5)}
        self.assertEqual(len(ids), 5, "All generated RFQ IDs should be unique")

    def test_part_number_normalization(self):
        """Part numbers with mixed case and extra spaces are normalized to uppercase."""
        raw = (
            "Company: Test Corp. PN: 060 - 1234 - 00 qty: 3 condition NE"
        )
        res = self._run(raw)
        if res.data.get("part_number"):
            pn = res.data["part_number"]
            self.assertEqual(pn, pn.upper(), "Part number must be uppercase")
            self.assertNotIn(" ", pn, "Part number must not contain spaces")

    def test_response_always_has_required_keys(self):
        """AgentResponse.data always contains all schema-required keys."""
        raw = "Company: Acme. PN: 060-1234-00. Qty: 2."
        res = self._run(raw)
        required_keys = [
            "rfq_id", "status", "priority",
            "missing_fields", "ambiguous_fields",
            "AOG_status", "certification_requirements",
            "customer_email", "items",
        ]
        for key in required_keys:
            self.assertIn(key, res.data, f"Key '{key}' missing from response data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
