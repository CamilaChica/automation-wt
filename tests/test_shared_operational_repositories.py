import os
from contextlib import asynccontextmanager
from pathlib import Path
import pytest

from models.operational_models import (
    AgentHandoffRecord,
    SupplierInventoryRowRecord,
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
from repositories.runtime import create_operational_repositories
from models.db_models import RFQ


def test_inventory_row_model_cascades_with_its_import():
    foreign_keys = SupplierInventoryRowRecord.__table__.c.import_id.foreign_keys

    assert len(foreign_keys) == 1
    foreign_key = next(iter(foreign_keys))
    assert foreign_key.target_fullname == "supplier_inventory_imports.id"
    assert foreign_key.ondelete == "CASCADE"


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

    assert status["inventory_postgres_mirror_enabled"] is False
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


def test_full_postgres_readiness_requires_all_repository_checks(monkeypatch):
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "true")
    monkeypatch.setattr(
        "services.persistence_status.operations_store",
        type("PostgresStoreStub", (), {
            "storage_engine": "postgresql",
            "path": None,
            "check_operational_schema": lambda self: {"ready": True, "missing_tables": []},
        })(),
    )
    checks = {"inventory": True, "rfq": True, "supplier": True, "quote": True}

    assert persistence_status(
        postgres_healthy=True,
        repository_checks=checks,
        migration_status={"ready": True},
    )[
        "full_operational_persistence_ready"
    ] is True

    for repository in checks:
        failed_checks = {**checks, repository: False}
        status = persistence_status(
            postgres_healthy=True,
            repository_checks=failed_checks,
            migration_status={"ready": True},
        )
        assert status["full_operational_persistence_ready"] is False
        assert status["postgres_repository_checks"][repository] is False

    status = persistence_status(
        postgres_healthy=True,
        repository_checks=checks,
        migration_status={"ready": False},
    )
    assert status["full_operational_persistence_ready"] is False


async def test_operational_repository_factory_injects_one_shared_session():
    class SessionStub:
        def __init__(self):
            self.probes = 0

        @asynccontextmanager
        async def begin_nested(self):
            yield

        async def execute(self, _statement):
            self.probes += 1

    session = SessionStub()
    repositories = create_operational_repositories(session)

    assert all(
        repository.session is session
        for repository in (repositories.inventory, repositories.rfq, repositories.supplier, repositories.quote)
    )
    assert await repositories.check_readiness() == {
        "inventory": True, "rfq": True, "supplier": True, "quote": True,
    }
    assert session.probes == 10


async def test_postgres_checker_requires_an_explicit_local_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.setattr("scripts.check_postgres.LOCAL_ENV_FILE", Path("missing-test.env"))
    from scripts.check_postgres import main

    assert await main() == 1
    assert "DATABASE_URL was not found" in capsys.readouterr().err


def test_alembic_inspection_is_read_only_and_remote_migrations_require_consent(monkeypatch):
    from services.alembic_safety import is_read_only_alembic_command, validate_alembic_target

    assert is_read_only_alembic_command("current") is True
    assert is_read_only_alembic_command(["current"]) is True
    assert is_read_only_alembic_command("history") is True
    assert is_read_only_alembic_command("upgrade") is False
    validate_alembic_target("current", "postgresql://user:pass@prod.example/db")

    monkeypatch.delenv("ALLOW_REMOTE_ALEMBIC_MIGRATIONS", raising=False)
    with pytest.raises(RuntimeError, match="Remote Alembic migrations"):
        validate_alembic_target("upgrade", "postgresql://user:pass@staging.example/db")
    monkeypatch.setenv("ALLOW_REMOTE_ALEMBIC_MIGRATIONS", "true")
    with pytest.raises(RuntimeError, match="Render migrations"):
        validate_alembic_target("upgrade", "postgresql://user:pass@db.render.com/db")
    monkeypatch.setenv("ALLOW_PRODUCTION_ALEMBIC_MIGRATIONS", "true")
    validate_alembic_target("upgrade", "postgresql://user:pass@db.render.com/db")


def test_local_development_database_must_be_local_and_disposable():
    from services.database_safety import validate_development_database_target

    validate_development_database_target(
        "postgresql://user:pass@localhost/winged_test_db", "development"
    )
    with pytest.raises(RuntimeError, match="must target a local database"):
        validate_development_database_target(
            "postgresql://user:pass@db.example/winged_test_db", "test"
        )
    with pytest.raises(RuntimeError, match="must target a local database"):
        validate_development_database_target(
            "postgresql://user:pass@localhost/winged_production_db", "development"
        )


def test_database_url_resolution_prefers_process_then_local_file(tmp_path, monkeypatch):
    from services.database_safety import resolve_database_url

    env_file = tmp_path / ".env.local"
    env_file.write_text("DATABASE_URL=postgresql://postgres:postgres@localhost/test_db\n")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)

    assert resolve_database_url(env_file).endswith("@localhost/test_db")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost/test_override")
    assert resolve_database_url(env_file).endswith("@localhost/test_override")


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
