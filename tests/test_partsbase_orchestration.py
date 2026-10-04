import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.db_service import db_service
from services.orchestration_service import OrchestrationService
from agents.base_agent import AgentResponse


class TestPartsBaseOrchestration(unittest.TestCase):
    def setUp(self):
        db_service.audit_logs.clear()

    def test_submission_uses_exact_requested_quantity_and_is_idempotent(self):
        service = OrchestrationService()
        partsbase = SimpleNamespace(
            credentials_configured=Mock(return_value=True),
            request_partsbase_quote=AsyncMock(return_value={"status": "sent"}),
        )
        store = SimpleNamespace(storage_engine="sqlite")

        with (
            patch("services.orchestration_service.operations_store", store),
            patch("services.partsbase_service.credentials_configured", partsbase.credentials_configured),
            patch("services.partsbase_service.request_partsbase_quote", partsbase.request_partsbase_quote),
        ):
            first = asyncio.run(service._request_partsbase_quote("RFQ-1", "abc123", 7))
            second = asyncio.run(service._request_partsbase_quote("RFQ-1", "ABC123", 7))

        self.assertEqual(first["status"], "sent")
        self.assertTrue(second["reused"])
        partsbase.request_partsbase_quote.assert_awaited_once_with(
            ["ABC123"], quantities={"ABC123": 7}
        )

    def test_missing_credentials_queue_operator_review_without_submission(self):
        service = OrchestrationService()
        store = SimpleNamespace(
            storage_engine="sqlite",
            enqueue_operator_review=Mock(),
        )
        with (
            patch("services.orchestration_service.operations_store", store),
            patch("services.partsbase_service.credentials_configured", return_value=False),
            patch("services.partsbase_service.request_partsbase_quote", new_callable=AsyncMock) as submit,
        ):
            result = asyncio.run(service._request_partsbase_quote("RFQ-2", "ABC123", 3))

        self.assertEqual(result["status"], "not_configured")
        submit.assert_not_awaited()
        store.enqueue_operator_review.assert_called_once()
        self.assertEqual(
            store.enqueue_operator_review.call_args.kwargs["extraction"]["quantity"],
            3,
        )

    def test_unknown_part_automatically_updates_customer_without_false_delivery_claims(self):
        service = object.__new__(OrchestrationService)
        service._load_pipeline_state = Mock(return_value={})
        service._requested_certification = Mock(return_value=None)
        service._request_partsbase_quote = AsyncMock(return_value={"status": "not_configured"})
        service.parts_intel_agent = SimpleNamespace(execute=AsyncMock(return_value=AgentResponse(
            success=False, error_message="Part not found",
        )))
        rfq = SimpleNamespace(
            id="RFQ-SYNTHETIC", automation_paused=False, status="Validating",
            customer_email="customer@example.invalid", customer_name="Synthetic Buyer",
            thread_id="customer-original-thread", raw_text="Need SYNTHETIC-001",
        )
        item = SimpleNamespace(
            id="ITEM-SYNTHETIC", requested_part_number="SYNTHETIC-001",
            quantity=2, condition_preference="NE",
        )
        with (
            patch("services.orchestration_service.db_service") as database,
            patch("services.orchestration_service.operations_store", SimpleNamespace(storage_engine="sqlite")),
            patch("services.orchestration_service.communication_service.request_part_quotes",
                  return_value=[]) as outreach,
            patch("services.orchestration_service.communication_service.send_rfq_sourcing_update") as update,
        ):
            database.get_rfq.return_value = rfq
            database.get_rfq_items.return_value = [item]
            result = asyncio.run(service.process_rfq_pipeline(rfq.id))
        self.assertEqual(result["status"], "Supplier_Sourcing")
        self.assertFalse(update.call_args.kwargs["supplier_contact_queued"])
        self.assertEqual(update.call_args.kwargs["reply_to"], "customer-original-thread")
        self.assertEqual(outreach.call_args.kwargs["rfq_id"], rfq.id)


if __name__ == "__main__":
    unittest.main()
