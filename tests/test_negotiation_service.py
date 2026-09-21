import unittest

from services.negotiation_service import NegotiationSession, NegotiationState


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
