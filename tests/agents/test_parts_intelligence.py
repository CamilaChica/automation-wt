import asyncio
import unittest
from unittest.mock import patch

from agents.parts_intelligence_agent import PartsIntelligenceAgent
from models.db_models import InventoryItem
from tools.tool_interfaces import CheckInventoryTool, SearchPartsCatalogTool


def run(coro):
    return asyncio.run(coro)


class TestPartsIntelligence(unittest.TestCase):
    def setUp(self):
        self.inventory_item = InventoryItem(
            id="INV-TEST",
            part_number="060-1234-00",
            serial_number="SN-TEST",
            quantity_available=5,
            condition_code="NE",
            warehouse_location="Aisle 3, Bin B4",
            unit_cost=1000.0,
            certificate_type="FAA 8130-3",
            has_full_trace=True,
        )

    def test_catalog_tool_reads_inventory_and_supplier_records(self):
        with (
            patch("tools.tool_interfaces.db_service.inventory", {"INV-TEST": self.inventory_item}),
            patch("tools.tool_interfaces.supplier_db.find_supplier_offers", return_value=[{
                "part_number": "060-1234-00",
                "description": "Radar receiver",
                "certificate_type": "FAA 8130-3",
                "condition_code": "NE",
            }]),
        ):
            result = run(SearchPartsCatalogTool().run({"part_number": "060-1234-00"}))

        self.assertTrue(result["found"])
        self.assertEqual(result["match_type"], "exact")
        self.assertEqual(result["parts"][0]["description"], "Radar receiver")
        self.assertEqual(result["parts"][0]["documentation_requirements"], ["FAA 8130-3"])
        self.assertEqual(result["parts"][0]["alternate_part_numbers"], [])

    def test_catalog_tool_does_not_infer_unknown_parts_or_alternates(self):
        with (
            patch("tools.tool_interfaces.db_service.inventory", {}),
            patch("tools.tool_interfaces.supplier_db.find_supplier_offers", return_value=[]),
        ):
            result = run(SearchPartsCatalogTool().run({"part_number": "999-999-99"}))

        self.assertEqual(result, {"found": False, "match_type": "none", "parts": []})

    def test_agent_uses_database_backed_part_details(self):
        with (
            patch("tools.tool_interfaces.db_service.inventory", {"INV-TEST": self.inventory_item}),
            patch("tools.tool_interfaces.supplier_db.find_supplier_offers", return_value=[]),
        ):
            result = run(PartsIntelligenceAgent().execute({"requested_part_number": " 060-1234-00 "}))

        self.assertTrue(result.success)
        self.assertEqual(result.data["resolved_part_number"], "060-1234-00")
        self.assertEqual(result.data["condition"], "NE")
        self.assertEqual(result.data["documentation_requirements"], ["FAA 8130-3"])
        self.assertEqual(result.data["alternate_part_numbers"], [])

    def test_unknown_part_is_escalated_without_fabricated_match(self):
        with (
            patch("tools.tool_interfaces.db_service.inventory", {}),
            patch("tools.tool_interfaces.supplier_db.find_supplier_offers", return_value=[]),
        ):
            result = run(PartsIntelligenceAgent().execute({"requested_part_number": "999-999-99"}))

        self.assertFalse(result.success)
        self.assertEqual(result.data["match_type"], "none")
        self.assertEqual(result.data["confidence_score"], 0.0)
        self.assertEqual(result.escalation_triggered.condition, "part_not_found")

    def test_invalid_part_format_is_escalated(self):
        result = run(PartsIntelligenceAgent().execute({"requested_part_number": "A@B/123"}))
        self.assertFalse(result.success)
        self.assertEqual(result.escalation_triggered.condition, "invalid_part_format")


class TestInventoryTool(unittest.TestCase):
    def test_inventory_tool_calculates_atp_from_persisted_records(self):
        rows = [
            InventoryItem(
                id="INV-1", part_number="060-1234-00", serial_number="SN-1",
                quantity_available=5, condition_code="NE",
                warehouse_location="Aisle 3, Bin B4", unit_cost=1000.0,
                certificate_type="FAA 8130-3", has_full_trace=True,
            ),
            InventoryItem(
                id="INV-2", part_number="060-1234-00", serial_number="SN-2",
                quantity_available=2, condition_code="NE",
                warehouse_location="Aisle 3, Bin B5", unit_cost=1000.0,
                certificate_type="FAA 8130-3", has_full_trace=True,
            ),
        ]
        with patch("tools.tool_interfaces.db_service.inventory", {str(i): row for i, row in enumerate(rows)}):
            result = run(CheckInventoryTool().run({"part_number": "060-1234-00", "quantity": 6}))

        self.assertEqual(result["quantity_on_hand"], 7)
        self.assertEqual(result["available_quantity"], 7)
        self.assertEqual(result["shortage_quantity"], 0)
        self.assertEqual(result["availability_status"], "IN_STOCK")

    def test_inventory_tool_reports_unknown_part_as_not_found(self):
        with patch("tools.tool_interfaces.db_service.inventory", {}):
            result = run(CheckInventoryTool().run({"part_number": "999-999-99", "quantity": 2}))

        self.assertEqual(result["availability_status"], "NOT_FOUND")
        self.assertEqual(result["available_quantity"], 0)
        self.assertEqual(result["shortage_quantity"], 2)


if __name__ == "__main__":
    unittest.main()
