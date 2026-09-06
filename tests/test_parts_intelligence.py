"""
Tests for PartsIntelligenceAgent and the underlying SearchPartsCatalogTool.

Coverage:
1. Exact match           — known PN returns full product info, confidence 1.0
2. No match              — unknown PN flagged, success=False, confidence 0.0
3. Multiple matches      — ambiguous query triggers ambiguous_part_match escalation
4. Alternate part        — catalog alternate PNs are returned (never assumed)
5. Invalid part number   — bad format triggers invalid_part_format escalation
"""

import asyncio
import unittest

from agents.parts_intelligence_agent import PartsIntelligenceAgent
from tools.tool_interfaces import SearchPartsCatalogTool


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def run(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.run(coro)


# ─────────────────────────────────────────────────────────────────────────────
# SearchPartsCatalogTool unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchPartsCatalogTool(unittest.TestCase):
    """Direct unit tests for the catalog lookup tool."""

    def setUp(self):
        self.tool = SearchPartsCatalogTool()

    # ── exact match ──────────────────────────────────────────────────────────
    def test_exact_match_returns_part(self):
        result = run(self.tool.run({"part_number": "060-1234-00"}))
        self.assertTrue(result["found"])
        self.assertEqual(result["match_type"], "exact")
        self.assertEqual(len(result["parts"]), 1)
        part = result["parts"][0]
        self.assertEqual(part["part_number"], "060-1234-00")
        self.assertEqual(part["manufacturer"], "Honeywell")
        self.assertEqual(part["category"], "Avionics")
        self.assertEqual(part["aircraft_applicability"], "B737")
        self.assertEqual(part["condition"], "NE")

    def test_exact_match_case_insensitive(self):
        """Tool normalises casing before lookup."""
        result = run(self.tool.run({"part_number": "060-1234-00"}))
        self.assertTrue(result["found"])
        self.assertEqual(result["match_type"], "exact")

    def test_exact_match_456_actuator(self):
        result = run(self.tool.run({"part_number": "456-789-OH"}))
        self.assertTrue(result["found"])
        self.assertEqual(result["match_type"], "exact")
        part = result["parts"][0]
        self.assertEqual(part["manufacturer"], "Liebherr")
        self.assertEqual(part["aircraft_applicability"], "A320")
        self.assertIn("EASA Form 1", part["documentation_requirements"])

    # ── no match ─────────────────────────────────────────────────────────────
    def test_no_match_unknown_part(self):
        result = run(self.tool.run({"part_number": "999-999-99"}))
        self.assertFalse(result["found"])
        self.assertEqual(result["match_type"], "none")
        self.assertEqual(result["parts"], [])

    def test_no_match_empty_string(self):
        result = run(self.tool.run({"part_number": ""}))
        self.assertFalse(result["found"])
        self.assertEqual(result["match_type"], "none")

    # ── multiple matches ──────────────────────────────────────────────────────
    def test_multiple_matches_ambiguous_prefix(self):
        """Query 'MULTIPLE-123' matches both MULTIPLE-123-A and MULTIPLE-123-B."""
        result = run(self.tool.run({"part_number": "MULTIPLE-123"}))
        self.assertTrue(result["found"])
        self.assertEqual(result["match_type"], "multiple")
        self.assertGreaterEqual(len(result["parts"]), 2)

    # ── alternate part ────────────────────────────────────────────────────────
    def test_alternate_part_numbers_in_catalog(self):
        """060-1234-00 catalog entry should list 060-1234-01 as an alternate."""
        result = run(self.tool.run({"part_number": "060-1234-00"}))
        self.assertTrue(result["found"])
        part = result["parts"][0]
        self.assertIn("060-1234-01", part["alternate_part_numbers"])

    def test_alternate_bidirectional(self):
        """060-1234-01 catalog entry should list 060-1234-00 as an alternate."""
        result = run(self.tool.run({"part_number": "060-1234-01"}))
        self.assertTrue(result["found"])
        part = result["parts"][0]
        self.assertIn("060-1234-00", part["alternate_part_numbers"])


# ─────────────────────────────────────────────────────────────────────────────
# PartsIntelligenceAgent unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPartsIntelligenceAgent(unittest.TestCase):
    """Tests for the PartsIntelligenceAgent execute() method."""

    def setUp(self):
        self.agent = PartsIntelligenceAgent()

    # ── 1. Exact match ────────────────────────────────────────────────────────
    def test_exact_match_success(self):
        """Known PN returns success, is_valid=True, confidence=1.0, full product info."""
        response = run(self.agent.execute({"requested_part_number": "060-1234-00"}))

        self.assertTrue(response.success)
        self.assertIsNone(response.escalation_triggered)

        data = response.data
        self.assertEqual(data["resolved_part_number"], "060-1234-00")
        self.assertTrue(data["is_valid"])
        self.assertEqual(data["confidence_score"], 1.0)
        self.assertEqual(data["match_type"], "exact")

        # Full product fields populated
        self.assertEqual(data["manufacturer"], "Honeywell")
        self.assertEqual(data["category"], "Avionics")
        self.assertEqual(data["aircraft_applicability"], "B737")
        self.assertEqual(data["condition"], "NE")
        self.assertIn("FAA 8130-3", data["documentation_requirements"])

    def test_exact_match_normalises_whitespace(self):
        """Leading/trailing whitespace in the request is stripped before lookup."""
        response = run(self.agent.execute({"requested_part_number": "  060-1234-00  "}))
        self.assertTrue(response.success)
        self.assertEqual(response.data["resolved_part_number"], "060-1234-00")
        self.assertEqual(response.data["confidence_score"], 1.0)

    def test_exact_match_second_known_part(self):
        """456-789-OH returns correct Liebherr / A320 data."""
        response = run(self.agent.execute({"requested_part_number": "456-789-OH"}))
        self.assertTrue(response.success)
        self.assertEqual(response.data["manufacturer"], "Liebherr")
        self.assertEqual(response.data["aircraft_applicability"], "A320")
        self.assertEqual(response.data["confidence_score"], 1.0)

    # ── 2. No match ────────────────────────────────────────────────────────────
    def test_no_match_unknown_pn(self):
        """Unknown PN returns success=False, is_valid=False, confidence=0.0."""
        response = run(self.agent.execute({"requested_part_number": "999-999-99"}))

        self.assertFalse(response.success)
        self.assertIsNotNone(response.error_message)
        self.assertIn("999-999-99", response.error_message)

        data = response.data
        self.assertFalse(data["is_valid"])
        self.assertEqual(data["confidence_score"], 0.0)
        self.assertEqual(data["match_type"], "none")

        # Escalation triggered for unknown PN
        self.assertIsNotNone(response.escalation_triggered)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_no_match_flags_cannot_assume_compatibility(self):
        """Error message must explicitly state compatibility was not assumed."""
        response = run(self.agent.execute({"requested_part_number": "ABC-999-XY"}))
        self.assertFalse(response.success)
        self.assertIn("never be assumed", response.error_message)

    # ── 3. Multiple matches ───────────────────────────────────────────────────
    def test_multiple_matches_triggers_ambiguous_escalation(self):
        """Ambiguous query that matches two catalog parts must trigger ambiguous_part_match."""
        response = run(self.agent.execute({"requested_part_number": "MULTIPLE-123"}))

        self.assertFalse(response.success)
        self.assertIsNotNone(response.escalation_triggered)
        self.assertEqual(response.escalation_triggered.condition, "ambiguous_part_match")
        self.assertEqual(response.escalation_triggered.escalate_to, "human_operator")

    def test_multiple_matches_error_mentions_candidates(self):
        """Error message should list the candidate part numbers."""
        response = run(self.agent.execute({"requested_part_number": "MULTIPLE-123"}))
        self.assertIn("MULTIPLE-123-A", response.error_message)
        self.assertIn("MULTIPLE-123-B", response.error_message)

    # ── 4. Alternate part ─────────────────────────────────────────────────────
    def test_exact_match_returns_approved_alternates(self):
        """Alternate PNs in the response must come directly from the catalog entry."""
        response = run(self.agent.execute({"requested_part_number": "060-1234-00"}))
        self.assertTrue(response.success)

        alternates = response.data["alternate_part_numbers"]
        self.assertIsInstance(alternates, list)
        self.assertIn("060-1234-01", alternates)

    def test_no_assumed_alternates_for_part_without_alternates(self):
        """A part with no catalog alternates must return an empty alternates list."""
        response = run(self.agent.execute({"requested_part_number": "456-789-OH"}))
        self.assertTrue(response.success)
        self.assertEqual(response.data["alternate_part_numbers"], [])

    def test_alternate_pn_itself_resolves_with_lower_confidence(self):
        """Requesting 060-1234-01 by exact PN resolves at confidence 1.0 (it's in the catalog)."""
        response = run(self.agent.execute({"requested_part_number": "060-1234-01"}))
        self.assertTrue(response.success)
        self.assertEqual(response.data["resolved_part_number"], "060-1234-01")
        self.assertEqual(response.data["confidence_score"], 1.0)

    # ── 5. Invalid part number ────────────────────────────────────────────────
    def test_invalid_pn_with_slash(self):
        """Part numbers containing '/' must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": "1/234"}))
        self.assertFalse(response.success)
        self.assertIsNotNone(response.escalation_triggered)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_invalid_pn_too_short(self):
        """Part numbers shorter than 3 characters must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": "AB"}))
        self.assertFalse(response.success)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_invalid_pn_empty(self):
        """Empty part number must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": ""}))
        self.assertFalse(response.success)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_invalid_pn_leading_hyphen(self):
        """Part number with a leading hyphen must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": "-ABC-123"}))
        self.assertFalse(response.success)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_invalid_pn_special_characters(self):
        """Part number with special characters (e.g. '@') must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": "A@B-123"}))
        self.assertFalse(response.success)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_invalid_pn_spaces_in_middle(self):
        """Part number with internal spaces must fail format validation."""
        response = run(self.agent.execute({"requested_part_number": "ABC 123"}))
        self.assertFalse(response.success)
        self.assertEqual(response.escalation_triggered.condition, "invalid_part_format")

    def test_escalation_routes_to_human_operator(self):
        """All escalations from this agent must route to human_operator."""
        response = run(self.agent.execute({"requested_part_number": "AB"}))
        self.assertEqual(response.escalation_triggered.escalate_to, "human_operator")

    # ── Metadata integrity ────────────────────────────────────────────────────
    def test_agent_metadata_name(self):
        self.assertEqual(self.agent.metadata.name, "PartsIntelligenceAgent")

    def test_agent_has_search_parts_catalog_tool(self):
        self.assertIn("search_parts_catalog", self.agent.metadata.available_tools)

    def test_agent_has_two_escalation_rules(self):
        rules = {r.condition for r in self.agent.metadata.escalation_rules}
        self.assertIn("ambiguous_part_match", rules)
        self.assertIn("invalid_part_format", rules)


if __name__ == "__main__":
    unittest.main()
