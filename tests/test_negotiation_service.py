import os
import tempfile
import unittest
from unittest.mock import patch

from services.negotiation_service import SupplierNegotiationService
from services.negotiation_service import NegotiationSession, NegotiationState
from services.operations_store import OperationsStore


class TestSupplierNegotiationService(unittest.TestCase):
    def test_line_value_threshold_and_bounded_rounds_respect_floor(self):
        scheduled = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "ENVIRONMENT": "local", "WT_ENV": "local", "WT_AUTH_ENV": "local", "RENDER": "false",
            "NEGOTIATION_MIN_LINE_VALUE": "500", "NEGOTIATION_FLOOR_DISCOUNT_PERCENT": "10",
            "NEGOTIATION_FIRST_DISCOUNT_PERCENT": "5", "NEGOTIATION_NEXT_DISCOUNT_PERCENT": "3",
            "SUPPLIER_DISCOUNT_MAX_ROUNDS": "3",
        }, clear=False):
            store = OperationsStore(os.path.join(directory, "negotiation.db"))
            with patch("services.negotiation_service.operations_store", store):
                service = SupplierNegotiationService(lambda **request: scheduled.append(request))
                below_threshold = service.record_supplier_quote(
                    supplier_email="seller@example.com", supplier_name="Seller", part_number="ABC-123",
                    quantity=1, unit_cost=100, source_email_id="email-1",
                )
                self.assertEqual(below_threshold["status"], "BELOW_THRESHOLD")

                first = service.record_supplier_quote(
                    supplier_email="seller@example.com", supplier_name="Seller", part_number="060-1234-00",
                    quantity=10, unit_cost=100, source_email_id="email-2",
                )
                second = service.record_supplier_quote(
                    supplier_email="seller@example.com", supplier_name="Seller", part_number="060-1234-00",
                    quantity=10, unit_cost=100, source_email_id="email-3",
                )
                third = service.record_supplier_quote(
                    supplier_email="seller@example.com", supplier_name="Seller", part_number="060-1234-00",
                    quantity=10, unit_cost=100, source_email_id="email-4",
                )

                self.assertEqual(first["round"], 1)
                self.assertEqual(second["round"], 2)
                self.assertEqual(third["round"], 3)
                self.assertEqual([request["round_number"] for request in scheduled], [1, 2, 3])
                self.assertGreaterEqual(scheduled[-1]["unit_cost"], 90)
                session = store.get_negotiation_session("seller@example.com", "060-1234-00")["session"]
                self.assertEqual(len(session["rounds"]), 3)
                self.assertEqual(session["minimum_unit_cost"], 90)


class TestNegotiationService(unittest.TestCase):
    def _session(self):
        return NegotiationSession(
            session_id="NEG-1",
            supplier_id="SUP-1",
            part_number="060-1234-00",
            initial_unit_cost=1000,
            minimum_unit_cost=900,
        )

    def test_round_trip_accepts_supplier_response(self):
        session = self._session()
        session.propose(950)
        response = session.record_response(925, accepted=True, note="Volume discount accepted")

        self.assertEqual(response.state, NegotiationState.DISCOUNT_ACCEPTED)
        self.assertEqual(session.state, NegotiationState.DISCOUNT_ACCEPTED)

    def test_floor_breach_escalates_without_counteroffer(self):
        session = self._session()

        with self.assertRaises(ValueError):
            session.propose(899)

        self.assertEqual(session.state, NegotiationState.ESCALATED)
        self.assertEqual(session.rounds, [])

    def test_round_limit_requires_human_review(self):
        session = self._session()
        session.propose(980)
        session.record_response(980, accepted=False)
        session.propose(950)
        session.record_response(950, accepted=False)

        self.assertEqual(session.state, NegotiationState.DISCOUNT_REJECTED)
        with self.assertRaises(ValueError):
            session.propose(925)


if __name__ == "__main__":
    unittest.main()
