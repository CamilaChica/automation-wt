import unittest
from types import SimpleNamespace

from services.voice_service import (
    check_inventory_availability,
    get_order_status,
    get_voice_dashboard,
    log_customer_concern,
)


class VoiceServiceTests(unittest.TestCase):
    def test_inventory_maps_only_supplied_live_records(self):
        inventory = [
            SimpleNamespace(
                part_number="LIVE-060-1234",
                quantity_available=4,
                condition_code="NE",
                certificate_type="FAA 8130-3",
                has_full_trace=True,
            ),
            SimpleNamespace(
                part_number="LIVE-060-5678",
                quantity_available=2,
                condition_code="OH",
                certificate_type="EASA Form 1",
                has_full_trace=False,
            ),
        ]
        exact = check_inventory_availability("LIVE-060-1234", inventory)
        partial = check_inventory_availability("060", inventory)

        self.assertEqual([item["quantity"] for item in exact["matches"]], [4])
        self.assertEqual(len(partial["matches"]), 2)
        self.assertNotIn("unit_cost", exact["matches"][0])
        self.assertEqual(check_inventory_availability("missing", [])['matches'], [])

    def test_order_status_maps_only_supplied_live_rfq(self):
        rfq = SimpleNamespace(
            id="WT-LIVE-48240",
            customer_name="Live Customer",
            part_number="LIVE-060-1234",
            status="Needs_Human_Review",
        )
        result = get_order_status("wt-live-48240", [rfq])

        self.assertTrue(result["found"])
        self.assertEqual(result["status"], "Needs_Human_Review")
        self.assertTrue(result["review_notice"])
        self.assertFalse(get_order_status("WT-48240", [rfq])["found"])

    def test_voice_dashboard_contains_only_supplied_records(self):
        rfq = SimpleNamespace(id="WT-LIVE-1", customer_name="Live Customer", part_number="LIVE-1", status="Quoted")
        inventory = SimpleNamespace(part_number="LIVE-1", quantity_available=3, condition_code="NE", certificate_type="CoC", has_full_trace=True)

        result = get_voice_dashboard([rfq], [inventory])

        self.assertEqual([item["id"] for item in result["requests"]], ["WT-LIVE-1"])
        self.assertEqual([item["part_number"] for item in result["inventory"]], ["LIVE-1"])
        self.assertNotIn("WT-48291", {item["id"] for item in result["requests"]})

    def test_export_control_concern_is_routed_to_operator(self):
        result = log_customer_concern("quote_follow_up", "ITAR-controlled item requested", "060-1234-00")

        self.assertTrue(result["requires_review"])
        self.assertEqual(result["concern"]["status"], "Escalated to operator")

    def test_routine_concern_is_logged_without_escalation(self):
        result = log_customer_concern("order_status", "Please confirm the delivery estimate", "10-60539-1")

        self.assertTrue(result["logged"])
        self.assertFalse(result["requires_review"])

    def test_ambiguous_or_non_usd_concern_is_routed_to_operator(self):
        ambiguous = log_customer_concern("quote_follow_up", "The requested terms are unclear", "060-1234-00")
        non_usd = log_customer_concern("quote_follow_up", "Customer asked for the amount in euros", "060-1234-00")

        self.assertTrue(ambiguous["requires_review"])
        self.assertTrue(non_usd["requires_review"])


if __name__ == "__main__":
    unittest.main()