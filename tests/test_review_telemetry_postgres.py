import os
import unittest
from unittest.mock import Mock, patch

from repositories.review_telemetry_repository import _sync_database_url
from services.operations_store import OperationsStore


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
        postgres = Mock()
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

    def test_production_operations_store_never_falls_back_to_sqlite(self):
        postgres = Mock()
        postgres.storage_engine = "postgresql"
        with (
            patch.dict(os.environ, {"ENVIRONMENT": "production", "DATABASE_URL": "postgresql://user:pass@db/app"}, clear=False),
            patch("services.operations_store.PostgresReviewTelemetryRepository", return_value=postgres),
        ):
            store = OperationsStore()
            with self.assertRaisesRegex(RuntimeError, "refusing SQLite fallback"):
                store.record_communication(
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

    def test_production_requires_database_url(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL is required"):
                OperationsStore()


if __name__ == "__main__":
    unittest.main()
