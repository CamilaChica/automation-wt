import os
import unittest
from unittest.mock import Mock, patch

from repositories.review_telemetry_repository import _sync_database_url
from services.operations_store import OperationsStore, POSTGRES_STORE_METHODS
from repositories.review_telemetry_repository import PostgresReviewTelemetryRepository


class TestReviewTelemetryPostgresRouting(unittest.TestCase):
    def test_database_url_is_converted_to_sync_psycopg2_driver(self):
        self.assertEqual(
            _sync_database_url("postgresql://user:pass@db.example/app"),
            "postgresql+psycopg2://user:pass@db.example/app",
        )
        self.assertEqual(
            _sync_database_url("postgresql+asyncpg://user:pass@db.example/app"),
            "postgresql+psycopg2://user:pass@db.example/app",
        )

    def test_production_operations_store_routes_review_and_telemetry_to_postgres(self):
        postgres = Mock(spec=PostgresReviewTelemetryRepository)
        postgres.storage_engine = "postgresql"
        postgres.enqueue_operator_review.return_value = "REV-PG-1"
        postgres.record_llm_telemetry.return_value = "LLM-PG-1"
        with (
            patch.dict(os.environ, {"ENVIRONMENT": "production", "DATABASE_URL": "postgresql://user:pass@db/app"}, clear=False),
            patch("services.operations_store.PostgresReviewTelemetryRepository", return_value=postgres),
        ):
            store = OperationsStore()
            review_id = store.enqueue_operator_review(
                idempotency_key="extract:case-1",
                task="rfq_extraction",
                source_text="Part Number: 060-1234-00",
                extraction={"part_number": "060-1234-00"},
                reason="low_confidence",
                prompt_version="rfq-extraction-v1",
            )
            telemetry_id = store.record_llm_telemetry(
                task="rfq_extraction",
                prompt_version="rfq-extraction-v1",
                model_id="gpt-4o-mini",
                model_calls=["gpt-4o-mini"],
                latency_ms=20,
                input_tokens=100,
                output_tokens=40,
                estimated_cost_usd=0.0001,
                validation_result="VALIDATED",
                review_queue_id=review_id,
            )

        self.assertEqual(store.storage_engine, "postgresql")
        self.assertEqual(review_id, "REV-PG-1")
        self.assertEqual(telemetry_id, "LLM-PG-1")
        postgres.enqueue_operator_review.assert_called_once()
        postgres.record_llm_telemetry.assert_called_once()

    def test_production_operations_store_routes_business_writes_to_postgres(self):
        postgres = Mock(spec=PostgresReviewTelemetryRepository)
        postgres.storage_engine = "postgresql"
        postgres.record_communication.return_value = "COM-PG-1"
        with (
            patch.dict(os.environ, {"ENVIRONMENT": "production", "DATABASE_URL": "postgresql://user:pass@db/app"}, clear=False),
            patch("services.operations_store.PostgresReviewTelemetryRepository", return_value=postgres),
        ):
            store = OperationsStore()
            communication_id = store.record_communication(
                entity_type="quote",
                entity_id="QTE-1",
                recipient="buyer@example.test",
                sender="sales@example.test",
                channel="email",
                subject="Quote",
                message="Review",
                message_type="outbound",
                status="DRY_RUN",
            )
            store.upsert_customer("CUS-1", "Buyer Co", "Buyer", "buyer@example.test")
            store.insert_rfq(
                rfq_id="RFQ-1", customer_id="CUS-1", part_number="060-1234-00",
                description="Part request", quantity=2, condition="NE", certification=None,
                destination=None, status="Intake", raw_text="request", thread_id=None,
            )
            store.update_rfq_status("RFQ-1", "Quote_Sent")
            store.insert_customer_quote(
                quote_id="QTE-1", rfq_id="RFQ-1", unit_price=20, quantity=2,
                total_price=40, lead_time=3, condition="NE", certification="8130-3",
                valid_until=None, status="Draft",
            )
            store.insert_customer_quote_item(
                item_id="QITM-1", quote_id="QTE-1", rfq_item_id="RITM-1",
                part_number="060-1234-00", description="Aircraft part", quantity=2,
                condition="NE", certification="8130-3", unit_price=20, lead_time=3,
            )
            self.assertTrue(store.claim_inbound_message("<message-1>", "sales"))
            store.mark_inbound_message_processed("<message-1>")

        self.assertEqual(communication_id, "COM-PG-1")
        postgres.record_communication.assert_called_once()
        postgres.upsert_customer.assert_called_once()
        postgres.insert_rfq.assert_called_once()
        postgres.update_rfq_status.assert_called_once_with("RFQ-1", "Quote_Sent")
        postgres.insert_customer_quote.assert_called_once()
        postgres.insert_customer_quote_item.assert_called_once()
        postgres.claim_inbound_message.assert_called_once_with("<message-1>", "sales")
        postgres.mark_inbound_message_processed.assert_called_once_with("<message-1>")

    def test_postgres_adapter_implements_every_store_method(self):
        for method in POSTGRES_STORE_METHODS:
            self.assertTrue(callable(getattr(PostgresReviewTelemetryRepository, method, None)), method)

    def test_nested_repository_transactions_share_one_connection(self):
        connection = object()
        transaction_context = Mock()
        transaction_context.__enter__ = Mock(return_value=connection)
        transaction_context.__exit__ = Mock(return_value=False)
        engine = Mock()
        engine.begin.return_value = transaction_context
        repository = PostgresReviewTelemetryRepository(engine=engine)

        with repository.transaction() as outer:
            with repository.transaction() as nested:
                with repository._begin() as write_connection:
                    self.assertIs(outer, connection)
                    self.assertIs(nested, connection)
                    self.assertIs(write_connection, connection)

        engine.begin.assert_called_once_with()

    def test_production_requires_database_url(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required"):
                OperationsStore()


if __name__ == "__main__":
    unittest.main()
