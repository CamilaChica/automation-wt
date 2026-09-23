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
