import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services import no_quote_service as nq

NOW = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)


def make_rfq(rfq_id="RFQ-1", hours_ago=49, status="Supplier_Sourcing", raw_text="Need P/N 123", **extra):
    data = dict(
        id=rfq_id, status=status, raw_text=raw_text, created_at=NOW - timedelta(hours=hours_ago),
        part_number="123", customer_email="buyer@example.com", customer_name="Buyer",
        thread_id="msg-1", automation_paused=False,
    )
    data.update(extra)
    return SimpleNamespace(**data)


class FakeDB:
    def __init__(self, rfqs, offers=None):
        self.rfqs = {r.id: r for r in rfqs}
        self.offers = offers or {}
        self.audit = []

    def list_rfqs(self):
        return list(self.rfqs.values())

    def get_rfq(self, rfq_id):
        return self.rfqs.get(rfq_id)

    def get_rfq_items(self, rfq_id):
        return []

    def get_supplier_offers_for_part(self, part):
        return self.offers.get(part, [])

    def update_rfq_status(self, rfq_id, status):
        self.rfqs[rfq_id].status = status

    def add_audit_log(self, rfq_id, actor, action, detail):
        self.audit.append((rfq_id, action))


class FakeComms:
    def __init__(self):
        self.sent = []

    def send_rfq_no_quote(self, **kwargs):
        self.sent.append(kwargs)


class NoQuoteRuleTests(unittest.TestCase):
    def test_overdue_rfq_without_offers_becomes_no_quote_and_replies_in_thread(self):
        db, comms = FakeDB([make_rfq()]), FakeComms()
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=comms), ["RFQ-1"])
        self.assertEqual(db.rfqs["RFQ-1"].status, "No_Quote")
        self.assertEqual(comms.sent[0]["reply_to"], "msg-1")
        self.assertEqual(comms.sent[0]["part_numbers"], ["123"])

    def test_standard_rfq_waits_48_hours(self):
        db, comms = FakeDB([make_rfq(hours_ago=47)]), FakeComms()
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=comms), [])
        self.assertEqual(comms.sent, [])

    def test_aog_rfq_closes_after_4_hours(self):
        db, comms = FakeDB([make_rfq(hours_ago=5, raw_text="AOG urgent P/N 123")]), FakeComms()
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=comms), ["RFQ-1"])

    def test_supplier_offer_prevents_no_quote(self):
        db, comms = FakeDB([make_rfq()], offers={"123": [{"price": 10}]}), FakeComms()
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=comms), [])
        self.assertEqual(db.rfqs["RFQ-1"].status, "Supplier_Sourcing")

    def test_paused_and_other_statuses_are_skipped(self):
        db = FakeDB([make_rfq("A", automation_paused=True), make_rfq("B", status="Quote_Sent")])
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=FakeComms()), [])

    def test_offer_lookup_error_is_fail_safe(self):
        db = FakeDB([make_rfq()])
        db.get_supplier_offers_for_part = lambda part: (_ for _ in ()).throw(RuntimeError("db down"))
        self.assertEqual(nq.sweep_no_quote(now=NOW, db=db, comms=FakeComms()), [])

    def test_late_offer_reopens_no_quote(self):
        db = FakeDB([make_rfq(status="No_Quote")])
        self.assertTrue(nq.reopen_if_no_quote(db, "RFQ-1"))
        self.assertEqual(db.rfqs["RFQ-1"].status, "Supplier_Sourcing")
        self.assertFalse(nq.reopen_if_no_quote(db, "RFQ-1"))


if __name__ == "__main__":
    unittest.main()
