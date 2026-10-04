import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.customer_reply_routing import (
    build_rfq_update_reply,
    company_name_for_sender,
    find_rfq_for_reply,
)
from services.email_templates import enforce_customer_email_policy


def rfq(rfq_id, email="buyer@mro.it", name="Acme MRO", status="Processing", days_ago=1):
    return SimpleNamespace(
        id=rfq_id, customer_email=email, customer_name=name, status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago), thread_id=None,
    )


class CustomerReplyRoutingTests(unittest.TestCase):
    def test_reply_with_re_subject_attaches_to_open_rfq(self):
        found = find_rfq_for_reply([rfq("RFQ-AAAAAA")], "Buyer@mro.it", "RE: RFQ received", "warranty?")
        self.assertEqual(found.id, "RFQ-AAAAAA")

    def test_rfq_reference_in_body_wins(self):
        rfqs = [rfq("RFQ-AAAAAA", days_ago=5), rfq("RFQ-BBBBBB", days_ago=1)]
        found = find_rfq_for_reply(rfqs, "buyer@mro.it", "question", "About RFQ-AAAAAA please")
        self.assertEqual(found.id, "RFQ-AAAAAA")

    def test_new_request_from_other_sender_is_not_matched(self):
        self.assertIsNone(find_rfq_for_reply([rfq("RFQ-AAAAAA")], "other@x.com", "RE: hi", ""))

    def test_company_name_from_portal_is_reused(self):
        rfqs = [rfq("RFQ-AAAAAA", name="Acme MRO"), rfq("RFQ-BBBBBB", name="Buyer")]
        self.assertEqual(company_name_for_sender(rfqs, "buyer@mro.it"), "Acme MRO")

    def test_reply_does_not_invent_quote_or_policy_details(self):
        body = build_rfq_update_reply(
            "RFQ-AAAAAA",
            "Do you ship to Italy? Will FAA 8130 be provided? Warranty 12 months?",
        )
        self.assertNotIn("ship worldwide", body)
        self.assertNotIn("8130-3", body)
        self.assertNotIn("Warranty:", body)
        self.assertNotIn("quotation is being prepared", body)
        self.assertIn("checking the details against your request", body)
        self.assertIn("follow up in this email thread", body)
        self.assertIn("There is no need to submit a new request", body)

    def test_greeting_never_uses_an_email_address(self):
        text = enforce_customer_email_policy("Hello", "buyer@mro.it")
        self.assertNotIn("@", text.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
