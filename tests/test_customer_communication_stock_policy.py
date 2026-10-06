import unittest
import asyncio

from services.email_templates import enforce_customer_email_policy
from tools.tool_interfaces import SearchPartsCatalogTool
from services.supplier_database import supplier_db


class TestCustomerCommunicationStockPolicy(unittest.TestCase):
    def test_enforce_customer_email_policy_replaces_supplier_sourcing_phrases(self):
        draft_body = (
            "Hi Valentina,\n\n"
            "We are currently getting the parts from the suppliers. "
            "Our team is arranging supplier confirmation for current price and availability. "
            "Please send your PO so we can secure the unit with our supplier.\n\n"
            "Best regards,\nWinged Tycoons Sales Team"
        )
        enforced = enforce_customer_email_policy(draft_body, "Aero Services Inc.", contact_name="Valentina")

        self.assertNotIn("getting the parts from the suppliers", enforced.lower())
        self.assertNotIn("with our supplier", enforced.lower())
        self.assertNotIn("arranging supplier confirmation", enforced.lower())

        self.assertIn("gathering the information from our current stock", enforced)
        self.assertIn("secure the unit from our current stock", enforced)

    def test_search_parts_catalog_matches_base_and_suffix(self):
        tool = SearchPartsCatalogTool()

        # Lookup with condition suffix
        res_suffix = asyncio.run(tool.run({"part_number": "456-789-OH"}))
        self.assertTrue(res_suffix["found"])
        self.assertEqual(res_suffix["parts"][0]["part_number"], "456-789")
        self.assertEqual(res_suffix["parts"][0]["description"], "Actuator Assembly (A320)")
        self.assertEqual(res_suffix["parts"][0]["condition"], "OH")

        # Lookup with base part number
        res_base = asyncio.run(tool.run({"part_number": "456-789"}))
        self.assertTrue(res_base["found"])
        self.assertEqual(res_base["parts"][0]["part_number"], "456-789")
        self.assertEqual(res_base["parts"][0]["description"], "Actuator Assembly (A320)")

    def test_find_supplier_offers_resolves_an960_and_456_789(self):
        # 456-789 query should match offer
        offers_456 = supplier_db.find_supplier_offers("456-789", quantity_needed=1)
        self.assertTrue(len(offers_456) > 0)
        self.assertEqual(offers_456[0]["part_number"], "456-789")
        self.assertEqual(offers_456[0]["description"], "Actuator Assembly (A320)")

        # AN960-416 query should return price >= 20.00
        offers_an = supplier_db.find_supplier_offers("AN960-416", quantity_needed=1)
        self.assertTrue(len(offers_an) > 0)
        self.assertEqual(offers_an[0]["part_number"], "AN960-416")
        self.assertGreaterEqual(offers_an[0]["unit_cost"], 20.00)
        self.assertEqual(offers_an[0]["description"], "Washer, Flat (Aircraft Hardware)")


if __name__ == "__main__":
    unittest.main()
