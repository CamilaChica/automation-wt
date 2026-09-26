import unittest

from services.voice_service import (
    check_inventory_availability,
    get_order_status,
    log_customer_concern,
)


class VoiceServiceTests(unittest.TestCase):
    def test_inventory_supports_exact_and_partial_part_numbers(self):
        exact = check_inventory_availability("060-1234-00")
        partial = check_inventory_availability("060")

        self.assertEqual([item["quantity"] for item in exact["matches"]], [4])
        self.assertEqual(len(partial["matches"]), 3)

    def test_order_status_returns_review_notice_for_escalated_demo_rfq(self):
        result = get_order_status("wt-48240")

        self.assertTrue(result["found"])
        self.assertEqual(result["status"], "Escalated to Sales")
        self.assertTrue(result["review_notice"])

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