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


async def test_async_email_purchase_order_uses_repository_and_outbox(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from models.db_models import Quote, QuoteItem
    from worker import _ingest_existing_sales_message_async

    rfq = RFQ(
        id="RFQ-ASYNC-EMAIL-PO-UNIT",
        customer_name="PO Buyer",
        customer_email="po-buyer@example.test",
        raw_text="Part P-PO-1 quantity 1",
        status="Quote_Sent",
    )
    quote = Quote(
        id="QTE-ASYNC-EMAIL-PO-UNIT",
        rfq_id=rfq.id,
        subtotal=125.0,
        total_amount=125.0,
        status="Sent",
    )
    quote_item = QuoteItem(
        id="QTI-ASYNC-EMAIL-PO-UNIT",
        quote_id=quote.id,
        rfq_item_id="RFI-ASYNC-EMAIL-PO-UNIT",
        part_number="P-PO-1",
        quantity=1,
        source="Inventory",
        unit_cost=100.0,
        unit_price=125.0,
        margin_percent=20.0,
        certificate_type="FAA 8130-3",
    )
    receive_po = AsyncMock(return_value=True)
    notify = AsyncMock(return_value={"transmission_status": "PENDING"})
    repositories = SimpleNamespace(
        rfq=SimpleNamespace(
            list_operational_records=AsyncMock(return_value={rfq.id: rfq.model_dump(mode="json")}),
            receive_purchase_order=receive_po,
        ),
        quote=SimpleNamespace(list_operational_records=AsyncMock(side_effect=[
            {quote.id: quote.model_dump(mode="json")},
            {quote_item.id: quote_item.model_dump(mode="json")},
        ])),
        supplier=SimpleNamespace(offers_for_part=AsyncMock(return_value=[])),
        records=SimpleNamespace(
            cancel_communication_task=AsyncMock(),
            enqueue_operator_review=AsyncMock(),
        ),
    )
    monkeypatch.setenv("CAMILA_NOTIFICATION_EMAIL", "review@example.test")
    monkeypatch.setattr("worker.communication_service.notify_purchase_order_async", notify)

    message = {
        "message_id": "MSG-ASYNC-EMAIL-PO-UNIT",
        "internet_message_id": "<async-email-po-unit@example.test>",
        "from": "PO Buyer <po-buyer@example.test>",
        "subject": "Purchase Order Number: WT-PO-ASYNC-UNIT",
        "body": "Please find our purchase order attached.",
        "attachments": [{
            "filename": "WT-PO-ASYNC-UNIT.pdf",
            "content_type": "application/pdf",
            "content": b"pdf",
        }],
    }

    assert await _ingest_existing_sales_message_async(message, repositories) is True

    receive_po.assert_awaited_once()
    assert receive_po.await_args.kwargs["po_number"] == "WT-PO-ASYNC-UNIT"
    assert receive_po.await_args.kwargs["received_message_id"] == message["internet_message_id"]
    assert receive_po.await_args.kwargs["attachment_metadata"][0]["size"] == 3
    notify.assert_awaited_once()
    assert notify.await_args.kwargs["recipient"] == "review@example.test"
    assert notify.await_args.kwargs["attachments"][0]["filename"] == "WT-PO-ASYNC-UNIT.pdf"
    assert notify.await_args.kwargs["attachments"][0]["content"] == b"pdf"
    repositories.records.enqueue_operator_review.assert_not_awaited()


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


def test_postgres_cutover_readiness_does_not_require_runtime_switch(monkeypatch):
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false")
    monkeypatch.setattr(
        "services.persistence_status.operations_store",
        type("PostgresStoreStub", (), {
            "storage_engine": "postgresql",
            "path": None,
            "check_operational_schema": lambda self: {"ready": True, "missing_tables": []},
        })(),
    )

    status = persistence_status(
        postgres_healthy=True,
        repository_checks={"inventory": True, "rfq": True, "supplier": True, "quote": True},
        migration_status={"ready": True},
    )

    assert status["operational_postgres_cutover_ready"] is True
    assert status["full_operational_persistence_ready"] is False


async def test_shipment_creation_queues_tracking_outbox_with_shipment_transaction(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from api import main

    call_order = []
    payloads = []

    class Records:
        async def upsert(self, domain, record_id, payload):
            payloads.append((domain, record_id, payload))
            call_order.append(domain)

        async def enqueue_outbox_message(self, **message):
            call_order.append("outbox")
            assert message["entity_id"] == payloads[0][1]
            assert payloads[0][2]["public_token"] in message["body"]
            return {"id": "OUT-SHIPMENT-1", "status": "PENDING"}

    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: call_order.append("commit")))
    repositories = SimpleNamespace(
        rfq=SimpleNamespace(get_operational_record=AsyncMock(return_value={
            "id": "RFQ-SHIP-ASYNC", "customer_name": "Buyer",
            "customer_email": "buyer@example.test", "raw_text": "Need part PN-1",
            "status": "In_Progress",
        })),
        records=Records(),
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "get_rfq", Mock(side_effect=AssertionError("sync RFQ read used")))
    monkeypatch.setattr(main.db_service, "create_shipment", Mock(side_effect=AssertionError("sync shipment write used")))
    monkeypatch.setattr(
        main.communication_service,
        "send_shipment_tracking_link",
        Mock(side_effect=AssertionError("synchronous shipment notifier used")),
    )

    response = await main.create_shipment(
        main.ShipmentCreateRequest(
            rfq_id="RFQ-SHIP-ASYNC", quote_id="QUOTE-SHIP-ASYNC",
            part_numbers=["PN-1"], quantity=2,
        ),
        _user={"role": "ROLE_ADMIN"},
        session=session,
    )

    assert [domain for domain, _, _ in payloads] == ["shipments", "shipment_events"]
    assert payloads[0][2]["status"] == "Preparing Shipment"
    assert payloads[1][2]["shipment_id"] == payloads[0][1]
    assert call_order == ["shipments", "shipment_events", "outbox", "commit"]
    assert response["shipment_id"] == payloads[0][1]
    assert response["tracking_notification"] == "PENDING"
    session.commit.assert_awaited_once()


async def test_async_shipment_creation_keeps_pending_po_review_block(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from fastapi import HTTPException

    from api import main

    upsert = AsyncMock()
    notification = Mock()
    repositories = SimpleNamespace(
        rfq=SimpleNamespace(get_operational_record=AsyncMock(return_value={
            "id": "RFQ-SHIP-BLOCKED", "customer_name": "Buyer",
            "customer_email": "buyer@example.test", "raw_text": "Need part PN-1",
            "status": "Pending_PO_Review",
        })),
        records=SimpleNamespace(upsert=upsert),
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.communication_service, "send_shipment_tracking_link", notification)

    with pytest.raises(HTTPException) as error:
        await main.create_shipment(
            main.ShipmentCreateRequest(
                rfq_id="RFQ-SHIP-BLOCKED", part_numbers=["PN-1"], quantity=1,
            ),
            _user={"role": "ROLE_ADMIN"},
            session=SimpleNamespace(commit=AsyncMock()),
        )

    assert error.value.status_code == 409
    upsert.assert_not_awaited()
    notification.assert_not_called()


async def test_purchase_order_approval_uses_atomic_async_repository(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from api import main

    session = SimpleNamespace(commit=AsyncMock())
    approve = AsyncMock(return_value=True)
    repositories = SimpleNamespace(
        quote=SimpleNamespace(get_operational_record=AsyncMock(return_value={
            "id": "QUOTE-APPROVE-ASYNC", "rfq_id": "RFQ-APPROVE-ASYNC",
        })),
        rfq=SimpleNamespace(
            get_operational_record=AsyncMock(return_value={
                "id": "RFQ-APPROVE-ASYNC", "customer_name": "Buyer",
                "customer_email": "buyer@example.test", "raw_text": "Need part PN-1",
                "status": "Pending_PO_Review",
            }),
            approve_purchase_order=approve,
        ),
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "get_quote", Mock(side_effect=AssertionError("sync quote read used")))
    monkeypatch.setattr(main.db_service, "get_rfq", Mock(side_effect=AssertionError("sync RFQ read used")))
    monkeypatch.setattr(
        main.orchestration_service,
        "approve_purchase_order",
        Mock(side_effect=AssertionError("sync PO approval used")),
    )

    response = await main.approve_purchase_order(
        "QUOTE-APPROVE-ASYNC",
        main.PurchaseOrderApprovalRequest(operator_name="Operator", comments="Documents verified."),
        _user={"role": "ROLE_ADMIN"},
        session=session,
    )

    assert response == {
        "status": "Purchase_Order_Received",
        "quote_id": "QUOTE-APPROVE-ASYNC",
        "rfq_id": "RFQ-APPROVE-ASYNC",
    }
    approve.assert_awaited_once_with(
        "RFQ-APPROVE-ASYNC", "QUOTE-APPROVE-ASYNC", "Operator", "Documents verified."
    )
    session.commit.assert_awaited_once()


async def test_quote_approval_route_uses_async_queue_coordinator(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from api import main

    session = SimpleNamespace(commit=AsyncMock())
    repositories = SimpleNamespace()
    approve = AsyncMock(return_value={
        "status": "Quote_Dispatch_Pending",
        "quote_id": "QTE-ASYNC-APPROVE",
        "transmission_status": "PENDING",
    })
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.orchestration_service, "approve_and_queue_quote_async", approve)
    monkeypatch.setattr(main.db_service, "get_quote", Mock(side_effect=AssertionError("sync quote read used")))

    response = await main.approve_quote(
        "QTE-ASYNC-APPROVE",
        main.ApproveRequest(
            operator_name="Operator", expected_version=4,
            items_override=[main.OverrideItem(quote_item_id="ITEM-1", unit_price=75.0)],
        ),
        _user={"role": "ROLE_ADMIN"},
        session=session,
    )

    assert response["status"] == "Quote_Dispatch_Pending"
    approve.assert_awaited_once_with(
        repositories,
        quote_id="QTE-ASYNC-APPROVE",
        operator_name="Operator",
        overrides=[{"quote_item_id": "ITEM-1", "unit_price": 75.0}],
        comments=None,
        expected_version=4,
    )
    session.commit.assert_awaited_once()


async def test_async_quote_approval_coordinator_drafts_and_queues_atomically(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agents.base_agent import AgentResponse
    from models.db_models import RFQ
    from services.orchestration_service import orchestration_service

    quote_payload = {
        "id": "QTE-ASYNC-COORDINATOR", "rfq_id": "RFQ-ASYNC-COORDINATOR",
        "status": "Pending_Approval", "subtotal": 50.0, "shipping_cost": 5.0,
        "total_amount": 55.0, "version": 3,
    }
    item_payload = {
        "id": "ITEM-ASYNC-COORDINATOR", "quote_id": "QTE-ASYNC-COORDINATOR",
        "part_number": "PN-ASYNC", "quantity": 2, "unit_price": 25.0,
        "unit_cost": 15.0,
    }
    records = SimpleNamespace(
        get=AsyncMock(return_value=quote_payload),
        list_by_payload_value=AsyncMock(return_value={item_payload["id"]: item_payload}),
        record_llm_telemetry=AsyncMock(),
        record_automation_event=AsyncMock(),
    )
    approve = AsyncMock(return_value=True)
    repositories = SimpleNamespace(
        records=records,
        quote=SimpleNamespace(approve_for_dispatch=approve),
        rfq=SimpleNamespace(session=SimpleNamespace(flush=AsyncMock()), add_audit_log=AsyncMock()),
    )
    draft = AgentResponse(success=True, data={
        "subject": "Quotation QTE-ASYNC-COORDINATOR",
        "formatted_body": "Approved quote details.",
        "telemetry": {"task": "customer_communication", "model_id": "template-fallback"},
        "automation_event": {"event_type": "llm_email_draft", "entity_id": "QTE-ASYNC-COORDINATOR"},
    })
    generate = AsyncMock(return_value=draft)
    enqueue = AsyncMock(return_value={"transmission_status": "PENDING"})
    followups = AsyncMock(return_value=[{"task_key": "customer-followup:QTE-ASYNC-COORDINATOR"}])
    rfq = RFQ(
        id="RFQ-ASYNC-COORDINATOR", customer_name="Buyer",
        customer_email="buyer@example.test", raw_text="Need PN-ASYNC", status="Pending_Approval",
    )
    monkeypatch.setattr("services.orchestration_service.db_service.get_rfq_async", AsyncMock(return_value=rfq))
    monkeypatch.setattr(orchestration_service.comm_agent, "execute", generate)
    monkeypatch.setattr(
        "services.orchestration_service.email_program_runtime.evaluate_policy",
        AsyncMock(return_value={"status": "available", "decision": "review"}),
    )
    monkeypatch.setattr("services.orchestration_service.communication_service.enqueue_customer_quote_async", enqueue)
    monkeypatch.setattr("services.orchestration_service.communication_service.schedule_customer_followups_async", followups)

    result = await orchestration_service.approve_and_queue_quote_async(
        repositories,
        quote_id="QTE-ASYNC-COORDINATOR",
        operator_name="Operator",
        overrides=[{"quote_item_id": "ITEM-ASYNC-COORDINATOR", "unit_price": 30.0}],
        comments="Reviewed.",
        expected_version=3,
    )

    assert result["status"] == "Quote_Dispatch_Pending"
    assert result["quote_id"] == "QTE-ASYNC-COORDINATOR"
    assert result["transmission_status"] == "PENDING"
    assert result["email_body"] == enqueue.await_args.kwargs["body"]
    assert "PN-ASYNC" in result["email_body"]
    assert "$30.00" in result["email_body"]
    assert result["email_body"] != draft.data["formatted_body"]
    assert generate.await_args.kwargs["context"] == {"draft_only": True}
    approved_payload = approve.await_args.kwargs["quote_payload"]
    assert approved_payload["status"] == "Pending_Approval"
    assert approved_payload["total_amount"] == 65.0
    assert approve.await_args.kwargs["item_payloads"][0]["unit_price"] == 30.0
    records.record_llm_telemetry.assert_awaited_once()
    records.record_automation_event.assert_awaited_once()
    enqueue.assert_awaited_once()
    followups.assert_awaited_once()
    repositories.rfq.add_audit_log.assert_awaited_once()
    assert repositories.rfq.add_audit_log.await_args.kwargs["action_type"] == "quote_policy_advisory"


async def test_quote_repository_loads_operational_quote_payload():
    from types import SimpleNamespace

    from models.operational_models import OperationalRecord
    from repositories.quote_repository import QuoteRepository

    class Session:
        async def get(self, model, key):
            assert model is OperationalRecord
            assert key == {"domain": "quotes", "record_id": "QUOTE-READ-ASYNC"}
            return SimpleNamespace(payload={"id": "QUOTE-READ-ASYNC", "rfq_id": "RFQ-1"})

    repository = QuoteRepository(Session())
    assert await repository.get_operational_record("quotes", "QUOTE-READ-ASYNC") == {
        "id": "QUOTE-READ-ASYNC", "rfq_id": "RFQ-1",
    }


async def test_quote_rejection_uses_atomic_async_repository(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from api import main

    session = SimpleNamespace(commit=AsyncMock())
    reject = AsyncMock(return_value=True)
    quote = {"id": "QUOTE-REJECT-ASYNC", "rfq_id": "RFQ-REJECT-ASYNC"}
    repositories = SimpleNamespace(
        quote=SimpleNamespace(get_operational_record=AsyncMock(return_value=quote)),
        rfq=SimpleNamespace(
            get_operational_record=AsyncMock(return_value={
                "id": "RFQ-REJECT-ASYNC", "customer_name": "Buyer",
                "customer_email": "buyer@example.test", "raw_text": "Need part PN-1",
                "status": "Quote_Sent",
            }),
            reject_quote=reject,
        ),
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "get_quote", Mock(side_effect=AssertionError("sync quote read used")))
    monkeypatch.setattr(main.db_service, "get_rfq", Mock(side_effect=AssertionError("sync RFQ read used")))
    monkeypatch.setattr(
        main.orchestration_service,
        "reject_quote",
        Mock(side_effect=AssertionError("sync quote rejection used")),
    )

    response = await main.reject_quote(
        "QUOTE-REJECT-ASYNC",
        main.RejectRequest(operator_name="Operator", comments="Pricing not accepted."),
        _user={"role": "ROLE_ADMIN"},
        session=session,
    )

    assert response == {"status": "Rejected", "quote_id": "QUOTE-REJECT-ASYNC"}
    reject.assert_awaited_once_with(
        "QUOTE-REJECT-ASYNC", "RFQ-REJECT-ASYNC", "Operator", "Pricing not accepted."
    )
    session.commit.assert_awaited_once()


async def test_async_purchase_order_submission_commits_outbox_with_review_state(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from api import main

    call_order = []
    receive = AsyncMock(side_effect=lambda **_kwargs: call_order.append("receive") or True)
    enqueue = AsyncMock(side_effect=lambda *_args, **_kwargs: call_order.append("enqueue") or {
        "mailbox": "sales", "recipient": "review@example.test",
        "subject": "PO review", "reply_to": None, "transmission_status": "PENDING",
        "communication_id": "OUT-PO-ASYNC", "outbox_id": "OUT-PO-ASYNC",
    })
    quote = {"id": "QTE-1001", "rfq_id": "RFQ-PO-ASYNC", "total_amount": 125.0, "status": "Sent"}
    repositories = SimpleNamespace(
        quote=SimpleNamespace(get_operational_record=AsyncMock(return_value=quote)),
        rfq=SimpleNamespace(
            get_operational_record=AsyncMock(return_value={
                "id": "RFQ-PO-ASYNC", "customer_name": "Buyer",
                "customer_email": "buyer@example.test", "raw_text": "Need PN-1",
                "status": "Quote_Sent",
            }),
            receive_purchase_order=receive,
        ),
        records=SimpleNamespace(list_by_payload_value=AsyncMock(return_value={
            "QITEM-1": {
                "id": "QITEM-1", "quote_id": "QTE-1001", "part_number": "PN-1",
                "quantity": 1, "unit_price": 125.0, "unit_cost": 80.0,
            },
        }), enqueue_outbox_message=enqueue),
        supplier=SimpleNamespace(offers_for_part=AsyncMock(return_value=[{
            "supplier_name": "Supplier", "supplier_email": "supplier@example.test",
            "unit_cost": 80.0,
        }])),
    )
    notification = AsyncMock(side_effect=lambda *_args, **_kwargs: call_order.append("notify") or {
        "transmission_status": "PENDING", "outbox_id": "OUT-PO-ASYNC",
    })
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: call_order.append("commit")))
    monkeypatch.setenv("CAMILA_NOTIFICATION_EMAIL", "review@example.test")
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.communication_service, "notify_purchase_order_async", notification)
    monkeypatch.setattr(main.db_service, "get_quote", Mock(side_effect=AssertionError("sync quote read used")))
    monkeypatch.setattr(main.db_service, "get_rfq", Mock(side_effect=AssertionError("sync RFQ read used")))
    from pathlib import Path
    import tempfile
    document_dir = Path(tempfile.mkdtemp())
    for attachment_id in ("ATT-1", "ATT-2", "ATT-3"):
        (document_dir / f"{attachment_id}.pdf").write_bytes(b"%PDF-1.4\n%test\n")
    monkeypatch.setattr(
        main.attachment_service,
        "get_stored_path",
        Mock(side_effect=lambda attachment_id: document_dir / f"{attachment_id}.pdf"),
    )
    monkeypatch.setattr(main.communication_service, "cancel_customer_followups_async", AsyncMock())
    monkeypatch.setattr(
        main.operations_store,
        "record_purchase_order",
        Mock(side_effect=AssertionError("sync PO persistence used")),
    )

    response = await main.submit_purchase_order(
        main.PurchaseOrderRequest(
            quote_id="QTE-1001", po_number="PO-1001",
            attachment_ids=["ATT-1", "ATT-2", "ATT-3"],
        ),
        user={"role": "ROLE_CUSTOMER", "email": "buyer@example.test"},
        session=session,
    )

    assert response["status"] == "Pending_PO_Review"
    assert response["internal_notification"]["transmission_status"] == "PENDING"
    receive.assert_awaited_once()
    notification.assert_awaited_once()
    assert [file["filename"] for file in notification.await_args.kwargs["attachments"]] == [
        "ATT-1.pdf", "ATT-2.pdf", "ATT-3.pdf",
    ]
    assert all(file["content"].startswith(b"%PDF-1.4") for file in notification.await_args.kwargs["attachments"])
    session.commit.assert_awaited_once()
    assert call_order == ["receive", "notify", "commit"]


async def test_async_purchase_order_duplicate_does_not_enqueue_notification(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from fastapi import HTTPException

    from api import main

    receive = AsyncMock(return_value=False)
    notification = AsyncMock()
    repositories = SimpleNamespace(
        quote=SimpleNamespace(get_operational_record=AsyncMock(return_value={
            "id": "QTE-1002", "rfq_id": "RFQ-PO-DUPLICATE", "total_amount": 50.0,
        })),
        rfq=SimpleNamespace(
            get_operational_record=AsyncMock(return_value={
                "id": "RFQ-PO-DUPLICATE", "customer_name": "Buyer",
                "customer_email": "buyer@example.test", "raw_text": "Need PN-1",
                "status": "Quote_Sent",
            }),
            receive_purchase_order=receive,
        ),
        records=SimpleNamespace(list_by_payload_value=AsyncMock(return_value={})),
        supplier=SimpleNamespace(offers_for_part=AsyncMock(return_value=[])),
    )
    monkeypatch.setenv("CAMILA_NOTIFICATION_EMAIL", "review@example.test")
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.communication_service, "notify_purchase_order_async", notification)

    with pytest.raises(HTTPException) as error:
        await main.submit_purchase_order(
            main.PurchaseOrderRequest(
                quote_id="QTE-1002", po_number="PO-1002",
                attachment_ids=["ATT-1", "ATT-2", "ATT-3"],
            ),
            user={"role": "ROLE_CUSTOMER", "email": "buyer@example.test"},
            session=SimpleNamespace(commit=AsyncMock()),
        )

    assert error.value.status_code == 409
    notification.assert_not_awaited()


async def test_async_purchase_order_notification_queues_without_direct_send(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from services.communication_service import communication_service

    enqueue = AsyncMock(return_value={
        "id": "OUT-PO-NOTIFY-1", "status": "PENDING", "retry_count": 0,
    })
    repositories = SimpleNamespace(records=SimpleNamespace(enqueue_outbox_message=enqueue))
    direct_send = Mock(side_effect=AssertionError("async notification must not send inline"))
    monkeypatch.setattr("services.communication_service.send_message", direct_send)

    result = await communication_service.notify_purchase_order_async(
        repositories,
        recipient="review@example.test",
        po_number="PO-1001",
        customer_name="Buyer",
        customer_email="buyer@example.test",
        quote_id="QTE-1001",
        items=[{
            "part_number": "PN-1", "quantity": 1, "unit_price": 125.0,
            "supplier_name": "Supplier", "supplier_unit_cost": 80.0,
        }],
        review_url="https://example.test/review",
    )

    queued_message = enqueue.await_args.kwargs
    assert len(queued_message["deduplication_key"]) == 64
    assert queued_message["mailbox"] == "sales"
    assert "PO-1001" in queued_message["body"]
    assert result["transmission_status"] == "PENDING"
    assert result["outbox_id"] == "OUT-PO-NOTIFY-1"
    direct_send.assert_not_called()


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
