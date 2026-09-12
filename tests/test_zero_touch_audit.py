import asyncio
import unittest

from services.db_service import db_service
from services.orchestration_service import orchestration_service


class TestZeroTouchAutonomousFlow(unittest.TestCase):
    def setUp(self):
        db_service.rfqs.clear()
        db_service.rfq_items.clear()
        db_service.quotes.clear()
        db_service.quote_items.clear()
        db_service.audit_logs.clear()
        db_service.seed_mock_data()

    def test_full_flow_has_no_manual_approval_flags(self):
        async def run_scenario():
            rfq = db_service.create_rfq(
                "Global Airlines",
                "mro.ops@globalairlines.com",
                "Please quote part 060-1234-00, quantity 1, for Global Airlines.",
            )
            pipeline = await orchestration_service.process_rfq_pipeline(rfq.id)
            self.assertEqual(pipeline.get("status"), "Pending_Approval")

            quote_id = pipeline["quote_id"]
            send_result = await orchestration_service.approve_and_send_quote(
                quote_id,
                "Autonomous Engine",
            )
            self.assertEqual(send_result.get("status"), "Quote_Sent")

            logs = db_service.get_audit_logs(rfq.id)
            manual_flags = [
                log
                for log in logs
                if log.status in {"WARNING", "FAILURE"}
            ]
            self.assertEqual(
                [],
                manual_flags,
                "Expected zero manual approval flags in clean autonomous scenario.",
            )

        asyncio.run(run_scenario())


if __name__ == "__main__":
    unittest.main()
