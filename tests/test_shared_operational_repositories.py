import os

from models.operational_models import (
    AgentHandoffRecord,
    AuditEventRecord,
    CommunicationRecord,
    CommunicationTaskRecord,
    InboundMessageIdempotencyRecord,
    QuoteItemRecord,
    QuoteRecord,
    RFQItemRecord,
    RFQRecord,
    SupplierOfferRecord,
    WorkflowStateRecord,
)
from services.persistence_status import persistence_status


def test_shared_operational_models_cover_all_required_domains():
    assert {
        RFQRecord.__tablename__, RFQItemRecord.__tablename__, SupplierOfferRecord.__tablename__,
        QuoteRecord.__tablename__, QuoteItemRecord.__tablename__, CommunicationRecord.__tablename__,
        AuditEventRecord.__tablename__, WorkflowStateRecord.__tablename__,
        CommunicationTaskRecord.__tablename__, InboundMessageIdempotencyRecord.__tablename__,
        AgentHandoffRecord.__tablename__,
    } == {
        "rfqs", "rfq_items", "supplier_offers", "quotes", "quote_items", "communications",
        "audit_events", "workflow_state", "communication_tasks", "inbound_message_idempotency",
        "agent_handoffs",
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


def test_production_refuses_sqlite_even_when_database_url_is_configured(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/production")
    from services.operations_store import OperationsStore

    try:
        OperationsStore(":memory:")
    except RuntimeError as exc:
        assert "not wired" in str(exc)
        assert "refusing to use SQLite" in str(exc)
    else:
        raise AssertionError("Production must not silently use SQLite operational storage")


def test_supplier_mirror_does_not_claim_sqlite_operations_are_postgres_primary(monkeypatch):
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")

    status = persistence_status(postgres_healthy=True)

    assert status["inventory_postgres_mirror_enabled"] is True
    assert status["storage_engine"] == "sqlite"
    assert status["operational_store"] == "sqlite_compatibility_store"
    assert status["postgres_primary_migration_required"] is True
