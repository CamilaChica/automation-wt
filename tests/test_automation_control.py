import asyncio
import unittest
import uuid

from services.db_service import db_service
from services.orchestration_service import orchestration_service


class TestAutomationControl(unittest.TestCase):
    def test_paused_rfq_does_not_enter_pipeline(self):
        rfq = db_service.create_rfq(
            customer_name="Automation Test",
            customer_email=f"automation-{uuid.uuid4().hex[:8]}@example.com",
            raw_text="Need one aviation part",
        )
        db_service.set_rfq_automation_paused(rfq.id, True, "Manual safety hold")

        result = asyncio.run(orchestration_service.process_rfq_pipeline(rfq.id))

        self.assertEqual(result["status"], "Automation_Paused")
        self.assertEqual(result["reason"], "Manual safety hold")
        self.assertEqual(db_service.get_rfq(rfq.id).status, "Intake")

        resumed = db_service.set_rfq_automation_paused(rfq.id, False)
        self.assertFalse(resumed.automation_paused)
        self.assertIsNone(resumed.pause_reason)


if __name__ == "__main__":
    unittest.main()
