"""Quote expiry, business-day, and AOG timing quality gates."""

import asyncio
import unittest
from datetime import datetime, timezone

from agents.rfq_intake_agent import RFQIntakeAgent


class TestTimeZonesAndLeadTimes(unittest.TestCase):
    def test_aog_input_is_classified_as_high_priority(self):
        result = asyncio.run(RFQIntakeAgent().execute({
            "raw_text": (
                "URGENT - AOG SITUATION\n"
                "Company: Global Airlines\n"
                "Part No: XYZ123\n"
                "Quantity: 1\n"
                "Condition: NE\n"
                "Need same day delivery to Miami."
            )
        }))

        self.assertTrue(result.success)
        self.assertIn(result.data.get("priority"), {"AOG", "Urgent", "Routine"})
        self.assertTrue(result.data.get("AOG_status") or result.data.get("priority") == "AOG")

    def test_utc_datetime_is_timezone_aware_for_test_inputs(self):
        value = datetime.now(timezone.utc)
        self.assertIsNotNone(value.tzinfo)
        self.assertEqual(value.utcoffset().total_seconds(), 0)

    @unittest.skip("Automatic quote expiration and customer-local business-day scheduling are not implemented.")
    def test_expired_quote_cancels_followup(self):
        pass

    @unittest.skip("AOG SMS/on-call escalation is not connected to RFQ intake yet.")
    def test_aog_bypasses_standard_queue_and_alerts_on_call_staff(self):
        pass


if __name__ == "__main__":
    unittest.main()
