import os

from models.operational_models import (
    AgentHandoffRecord,
    AuditEventRecord,
    CommunicationRecord,
    CommunicationTaskRecord,
    InboundMessageIdempotencyRecord,
    LLMTelemetryRecord,
    OperatorReviewRecord,
    AutomationEventRecord,
    CarrierWebhookEventRecord,
    OperationsStateRecord,
    QuoteItemRecord,
    QuoteRecord,
    RFQItemRecord,
    RFQRecord,
    SupplierOfferRecord,
    WorkflowStateRecord,
    CustomerRecord,
    CustomerQuoteRecord,
    CustomerQuoteItemRecord,
)
from models.db_models import AgentAuditLog, RFQ, Shipment, ShipmentEvent
from services.persistence_status import persistence_status
from models.db_models import RFQ


def test_shared_operational_models_cover_all_required_domains():
    assert {
        RFQRecord.__tablename__, RFQItemRecord.__tablename__, SupplierOfferRecord.__tablename__,
        QuoteRecord.__tablename__, QuoteItemRecord.__tablename__, CommunicationRecord.__tablename__,
        AuditEventRecord.__tablename__, WorkflowStateRecord.__tablename__,
        CommunicationTaskRecord.__tablename__, InboundMessageIdempotencyRecord.__tablename__,
        AgentHandoffRecord.__tablename__, OperatorReviewRecord.__tablename__,
        LLMTelemetryRecord.__tablename__, AutomationEventRecord.__tablename__,
        CarrierWebhookEventRecord.__tablename__, OperationsStateRecord.__tablename__,
        CustomerRecord.__tablename__, CustomerQuoteRecord.__tablename__,
        CustomerQuoteItemRecord.__tablename__,
    } == {
        "rfqs", "rfq_items", "supplier_offers", "quotes", "quote_items", "communications",
        "audit_events", "workflow_state", "communication_tasks", "inbound_message_idempotency",
        "agent_handoffs", "operator_review_queue", "llm_telemetry", "automation_events",
        "carrier_webhook_events", "operations_state", "customers", "customer_quotes",
        "customer_quote_items",
    }


def test_production_sqlite_operational_fallback_requires_database_url(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from services.operations_store import OperationsStore

    try:
        OperationsStore(":memory:")
    except RuntimeError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("Production operational storage must require DATABASE_URL")


def test_production_routes_review_store_to_postgres_without_sqlite_fallback(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/production")
    from services.operations_store import OperationsStore

    store = OperationsStore(":memory:")
    assert store.storage_engine == "postgresql"
    assert store.path is None
    try:
        store._connect()
    except RuntimeError as exc:
        assert "refusing SQLite fallback" in str(exc)
    else:
        raise AssertionError("Production must never open SQLite operational state")


def test_supplier_mirror_does_not_claim_sqlite_operations_are_postgres_primary(monkeypatch):
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")

    status = persistence_status(postgres_healthy=True)

    assert status["inventory_postgres_mirror_enabled"] is True
    assert status["storage_engine"] == "sqlite"
    assert status["operational_store"] == "sqlite_compatibility_store"
    assert status["postgres_primary_migration_required"] is True


def test_domain_model_timestamp_defaults_are_aware_utc():
    defaults = [
        RFQ(id="RFQ-UTC", customer_name="Buyer", customer_email="buyer@example.test", raw_text="request").created_at,
        ShipmentEvent(id="EVT-UTC", shipment_id="SHP-UTC", status="In Transit", description="Departed").occurred_at,
        Shipment(id="SHP-UTC", rfq_id="RFQ-UTC", customer_email="buyer@example.test", public_token="token").created_at,
        Shipment(id="SHP-UTC-2", rfq_id="RFQ-UTC", customer_email="buyer@example.test", public_token="token").updated_at,
        AgentAuditLog(rfq_id="RFQ-UTC", agent_name="test", action_type="test", message="test").timestamp,
    ]
    for value in defaults:
        assert value.tzinfo is not None
        assert value.utcoffset().total_seconds() == 0


def test_review_telemetry_postgres_does_not_claim_full_production_readiness(monkeypatch):
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/production")
    monkeypatch.setattr(
        "services.persistence_status.operations_store",
        type("PostgresStoreStub", (), {"storage_engine": "postgresql", "path": None})(),
    )
    status = persistence_status(postgres_healthy=True)

    assert status["storage_engine"] == "postgresql"
    assert status["operational_store"] == "postgresql_store_adapter_runtime_incomplete"
    assert status["postgres_store_adapter_complete"] is True
    assert status["postgres_primary_migration_required"] is True
    assert status["full_operational_persistence_ready"] is False


def test_production_db_service_reads_shared_rfq_records(monkeypatch):
    from services.db_service import MockDatabaseService

    rfq = RFQ(
        id="RFQ-SHARED", customer_name="Buyer", customer_email="buyer@example.test",
        raw_text="Need part", status="Intake",
    )
    store = type("SharedStoreStub", (), {
        "storage_engine": "postgresql",
        "list_operational_records": lambda self, domain: {rfq.id: rfq.model_dump(mode="json")},
    })()
    monkeypatch.setattr("services.db_service.operations_store", store)
    service = MockDatabaseService.__new__(MockDatabaseService)
    service._production = True

    assert [item.id for item in service.list_rfqs()] == ["RFQ-SHARED"]
    try:
        service._persist_state()
    except RuntimeError as exc:
        assert "Whole-state snapshots are disabled" in str(exc)
    else:
        raise AssertionError("Production must not save whole-state snapshots")
