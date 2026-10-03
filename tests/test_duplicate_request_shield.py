import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.customer_reply_routing import build_resurfaced_quote_text, find_recent_valid_quote

NOW = datetime(2025, 6, 10, tzinfo=timezone.utc)
SENDER = "buyer@mro.example"


def _fixtures(status="Quote_Sent", valid_until="2025-06-20", created=NOW - timedelta(days=3)):
    rfq = SimpleNamespace(id="RFQ-1", customer_email=SENDER, customer_name="Acme MRO", status=status,
                          created_at=created, thread_id="<t1>")
    quote = SimpleNamespace(id="QTE-1", rfq_id="RFQ-1", valid_until=valid_until)
    item = SimpleNamespace(quote_id="QTE-1", part_number="129666-3", quantity=2, unit_price=1500.0,
                           condition="OH", certificate_type="8130-3", lead_time_days=3)
    return [rfq], [quote], [item]


class FindRecentValidQuoteTests(unittest.TestCase):
    def test_match_for_same_part(self):
        match = find_recent_valid_quote(*_fixtures(), SENDER, "Please quote P/N 129666-3 qty 2", now=NOW)
        self.assertIsNotNone(match)
        rfq, quote, matched, qty_changed = match
        self.assertEqual((rfq.id, quote.id, len(matched), qty_changed), ("RFQ-1", "QTE-1", 1, False))

    def test_new_part_falls_through(self):
        self.assertIsNone(find_recent_valid_quote(*_fixtures(), SENDER, "Need 129666-3 and 65-1234-5", now=NOW))

    def test_expired_quote_falls_through(self):
        self.assertIsNone(find_recent_valid_quote(*_fixtures(valid_until="2025-06-01"), SENDER, "129666-3", now=NOW))

    def test_old_rfq_falls_through(self):
        fx = _fixtures(created=NOW - timedelta(days=45))
        self.assertIsNone(find_recent_valid_quote(*fx, SENDER, "129666-3", now=NOW))

    def test_other_sender_falls_through(self):
        self.assertIsNone(find_recent_valid_quote(*_fixtures(), "other@x.example", "129666-3", now=NOW))

    def test_unquoted_status_falls_through(self):
        self.assertIsNone(find_recent_valid_quote(*_fixtures(status="Sourcing"), SENDER, "129666-3", now=NOW))

    def test_quantity_change_is_noted(self):
        match = find_recent_valid_quote(*_fixtures(), SENDER, "P/N 1296663 qty: 5", now=NOW)
        self.assertIsNone(match)  # no dash -> not a recognised P/N token
        match = find_recent_valid_quote(*_fixtures(), SENDER, "P/N 129666-3 qty: 5", now=NOW)
        self.assertTrue(match[3])
        text = build_resurfaced_quote_text(match[1], match[2], match[3])
        self.assertIn("QTE-1", text)
        self.assertIn("updated quantity", text)


class AsyncShieldHookTests(unittest.TestCase):
    def test_async_hook_resends_quote_without_new_rfq(self):
        import worker

        rfqs, quotes, items = _fixtures(valid_until=(datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat(),
                                        created=datetime.now(timezone.utc) - timedelta(days=1))
        repositories = MagicMock()
        repositories.rfq.add_audit_log = AsyncMock()
        repositories.quote.list_operational_records = AsyncMock(side_effect=[
            {"QTE-1": {"id": "QTE-1", "rfq_id": "RFQ-1", "total_amount": 3000.0, "valid_until": quotes[0].valid_until}},
            {"I1": {"id": "I1", "quote_id": "QTE-1", "rfq_item_id": "RI1", "part_number": "129666-3",
                    "quantity": 2, "source": "Supplier", "unit_cost": 1200.0, "unit_price": 1500.0,
                    "margin_percent": 20.0, "condition": "OH", "certificate_type": "8130-3", "lead_time_days": 3},
                    "bad": {"quote_id": "QTE-1"}},
        ])
        message = {"from": f"Buyer <{SENDER}>", "subject": "RFQ 129666-3", "body": "Need 129666-3 qty 2",
                   "message_id": "<m2>"}
        with patch.object(worker.db_service, "list_rfqs_async", AsyncMock(return_value=rfqs)), \
                patch.object(worker.communication_service, "send_rfq_update_reply_async", AsyncMock()) as reply:
            handled = asyncio.run(worker._resend_existing_quote_async(message, repositories))
        self.assertTrue(handled)
        reply.assert_awaited_once()
        self.assertIn("QTE-1", reply.await_args.kwargs["quote_answer"])
        self.assertEqual(reply.await_args.kwargs["customer_name"], "Acme MRO")


if __name__ == "__main__":
    unittest.main()
