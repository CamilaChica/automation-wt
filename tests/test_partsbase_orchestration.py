import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.db_service import db_service
from services.orchestration_service import OrchestrationService
from agents.base_agent import AgentResponse


class TestPartsBaseOrchestration(unittest.TestCase):
    def test_historical_reference_is_customer_price_not_supplier_cost(self):
        offer = {"currency": "USD", "approval_status": "Approved", "unit_cost": 100,
                 "certificate_type": "FAA 8130-3", "source_received_at": "2026-01-01T00:00:00Z"}
        self.assertEqual(OrchestrationService._historical_reference_price([offer], 1), 125.0)
        for change in ({"currency": "EUR"}, {"currency": None}, {"approval_status": "Pending"},
                       {"certificate_type": None}, {"unit_cost": 0}):
            with self.subTest(change=change):
                self.assertIsNone(OrchestrationService._historical_reference_price([{**offer, **change}], 1))

    def test_catalog_uses_shared_postgres_not_local_supplier_database(self):
        from tools.tool_interfaces import SearchPartsCatalogTool
        with (
            patch("tools.tool_interfaces.db_service") as database,
            patch("tools.tool_interfaces.operations_store") as store,
            patch("tools.tool_interfaces.supplier_db.find_supplier_offers") as local,
        ):
            database.inventory.values.return_value = []
            store.storage_engine = "postgresql"
            store.get_supplier_offers.return_value = [{"part_number": "ABC123"}]
            result = asyncio.run(SearchPartsCatalogTool().run({"part_number": "ABC123"}))
        self.assertTrue(result["found"])
        store.get_supplier_offers.assert_called_once_with("ABC123", 1)
        local.assert_not_called()

    def test_sourcing_baseline_does_not_disclose_source_price_age_or_supplier(self):
        from services.communication_service import CommunicationService
        service = CommunicationService()
        with patch.object(service, "_send") as send:
            service.send_rfq_sourcing_update(
                recipient="buyer@example.invalid", customer_name="Buyer", rfq_id="RFQ-1",
                part_number="ABC123", historical_offer_date="2020-01-01", indicative_unit_price=125,
            )
        body = send.call_args.args[3]
        self.assertIn("USD 125.00", body)
        self.assertIn("non-binding", body)
        for forbidden in ("2020-01-01", "older than", "30 days", "supplier cost", "100.00"):
            self.assertNotIn(forbidden, body)

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

    def test_no_results_and_provider_failure_are_distinct(self):
        from services.partsbase_service import PartsBaseNoResults
        for error, status in (
            (PartsBaseNoResults("No matching listings"), "not_found"),
            (TimeoutError("search timed out"), "submission_unknown"),
        ):
            service = OrchestrationService()
            store = SimpleNamespace(storage_engine="sqlite", enqueue_operator_review=Mock())
            with (
                self.subTest(status=status),
                patch("services.orchestration_service.operations_store", store),
                patch("services.partsbase_service.credentials_configured", return_value=True),
                patch("services.partsbase_service.request_partsbase_quote",
                      new=AsyncMock(side_effect=error)),
            ):
                result = asyncio.run(service._request_partsbase_quote("RFQ-ERR", "ABC123", 3))
                self.assertEqual(result["status"], status)

    def test_retrieval_failure_halts_without_supplier_or_customer_email(self):
        service = OrchestrationService()
        rfq = SimpleNamespace(id="RFQ-FAULT", automation_paused=False, status="Validating")
        item = SimpleNamespace(id="ITEM-FAULT", requested_part_number="ABC123")
        service.parts_intel_agent.execute = AsyncMock(side_effect=ConnectionError("database unavailable"))
        with (
            patch("services.orchestration_service.db_service") as database,
            patch("services.orchestration_service.operations_store") as store,
            patch("services.orchestration_service.communication_service") as communication,
        ):
            database.get_rfq.return_value = rfq
            database.get_rfq_items.return_value = [item]
            result = asyncio.run(service.process_rfq_pipeline(rfq.id))
        self.assertEqual(result["status"], "Verification_Halted")
        self.assertEqual(result["diagnosis"], "system_error")
        store.enqueue_operator_review.assert_called_once()
        communication.request_part_quotes.assert_not_called()
        communication.send_rfq_sourcing_update.assert_not_called()

    def test_unknown_part_automatically_updates_customer_without_false_delivery_claims(self):
        service = object.__new__(OrchestrationService)
        service._load_pipeline_state = Mock(return_value={})
        service._requested_certification = Mock(return_value=None)
        service._request_partsbase_quote = AsyncMock(return_value={"status": "not_configured"})
        service.parts_intel_agent = SimpleNamespace(execute=AsyncMock(return_value=AgentResponse(
            success=False, error_message="Part not found", data={"match_type": "none"},
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
