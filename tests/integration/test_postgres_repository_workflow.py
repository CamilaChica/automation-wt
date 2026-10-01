from datetime import datetime, timedelta, timezone
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing

import pytest
from sqlalchemy import create_engine, func, select, text
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from api.auth import current_user
from api.main import app
from models.db_models import RFQ, Shipment
from models.operational_models import (
    AutomationEventRecord,
    InboundMessageIdempotencyRecord,
    OperationalRecord,
    RawEmailRecord,
    SupplierInventoryRowRecord,
)
from repositories.review_telemetry_repository import PostgresReviewTelemetryRepository
from repositories.review_telemetry_repository import inbound_dedupe_key
from services.async_database import get_async_db, session_scope
from repositories.runtime import create_operational_repositories
from services.supplier_database import PostgresSupplierDatabase


def _claim_inbound_message_in_process(connection_url: str, message_id: str) -> bool:
    engine = create_engine(connection_url, pool_size=1, max_overflow=0)
    try:
        repository = PostgresReviewTelemetryRepository(engine=engine)
        return repository.claim_inbound_message(message_id, "purchasing")
    finally:
        engine.dispose()


async def test_postgres_rfq_supplier_inventory_quote_persistence(disposable_postgres_engine):
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create(
            id="RFQ-POSTGRES-1",
            customer_email="buyer@example.test",
            customer_name="Test Buyer",
            raw_text="Need one verified test part",
        )
        await repositories.rfq.add_item(
            id="RFQ-ITEM-POSTGRES-1",
            rfq_id="RFQ-POSTGRES-1",
            part_number="TEST-PART-1",
            quantity=1,
        )
        supplier = await repositories.supplier.create(
            id="SUP-POSTGRES-1",
            company_name="Disposable Supplier",
            email="sales@example.test",
        )
        await repositories.supplier.create_part(
            id="SUP-PART-POSTGRES-1",
            supplier_id=supplier.id,
            part_number="TEST-PART-1",
            quantity_available=3,
        )
        await repositories.inventory.create_import(
            id="INV-IMPORT-POSTGRES-1",
            mailbox="purchasing",
            source_message_id="MSG-POSTGRES-1",
            filename="inventory.csv",
            content_sha256="a" * 64,
            parser="csv",
            status="imported",
        )
        await repositories.inventory.add_rows([{
            "id": "INV-ROW-POSTGRES-1",
            "import_id": "INV-IMPORT-POSTGRES-1",
            "row_number": 1,
            "part_number": "TEST-PART-1",
            "quantity_available": 3,
            "status": "imported",
            "raw_values": {"part_number": "TEST-PART-1", "quantity": "3"},
        }])
        await repositories.quote.create(
            id="QUOTE-POSTGRES-1",
            rfq_id="RFQ-POSTGRES-1",
            total_amount=125.0,
        )
        await repositories.quote.add_item(
            id="QUOTE-ITEM-POSTGRES-1",
            quote_id="QUOTE-POSTGRES-1",
            part_number="TEST-PART-1",
            quantity=1,
            unit_price=125.0,
        )
        await repositories.quote.set_status("QUOTE-POSTGRES-1", "Draft")

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        assert await repositories.check_readiness() == {
            "inventory": True, "rfq": True, "supplier": True, "quote": True,
        }
        assert await repositories.rfq.get("RFQ-POSTGRES-1") is not None
        assert await repositories.supplier.by_email("SALES@example.test") is not None
        assert len(await repositories.supplier.parts_for_supplier("SUP-POSTGRES-1")) == 1
        inventory_import = await repositories.inventory.import_for_source(
            "MSG-POSTGRES-1", "a" * 64
        )
        assert inventory_import is not None
        assert len(await repositories.inventory.rows_for_import(inventory_import.id)) == 1
        assert await repositories.quote.get("QUOTE-POSTGRES-1") is not None
        assert len(await repositories.quote.for_rfq("RFQ-POSTGRES-1")) == 1

    try:
        async with session_scope(disposable_postgres_engine) as session:
            repositories = create_operational_repositories(session)
            await repositories.rfq.create(
                id="RFQ-POSTGRES-ROLLBACK",
                customer_email="rollback@example.test",
                customer_name="Rollback Buyer",
                raw_text="This write must roll back",
            )
            raise RuntimeError("exercise transaction rollback")
    except RuntimeError as exc:
        assert str(exc) == "exercise transaction rollback"

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        assert await repositories.rfq.get("RFQ-POSTGRES-ROLLBACK") is None
        row_count = await session.scalar(select(func.count()).select_from(SupplierInventoryRowRecord))
        assert row_count == 1


async def test_postgres_supplier_database_facade_uses_shared_tables(disposable_postgres_engine):
    async with disposable_postgres_engine.connect() as connection:
        schema_name = await connection.scalar(text("SELECT current_schema()"))

    sync_url = disposable_postgres_engine.url.set(
        drivername="postgresql+psycopg2"
    ).update_query_dict({"options": f"-csearch_path={schema_name}"})
    sync_engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        repository = PostgresReviewTelemetryRepository(engine=sync_engine)
        database = PostgresSupplierDatabase(repository)
        offer = database.save_supplier_offer(
            supplier_name="Facade Integration Supplier",
            supplier_email="facade-integration@example.test",
            part_number="FACADE-TEST-PART",
            quantity_available=4,
            unit_cost=25.0,
            approval_status="Approved",
            source_email_id="facade-integration-message-1",
        )
        assert database.find_supplier_offers("facade-test-part", 2)[0]["supplier_part_id"] == offer["id"]
        assert database.search_supplier_offers("facade-test")[0]["supplier_part_id"] == offer["id"]
        assert database.list_suppliers()[0]["email"] == "facade-integration@example.test"

        saved_email_id = database.save_email(
            "purchasing",
            "facade-integration-message-1",
            "facade-integration@example.test",
            "Inventory update",
            "Test body",
        )
        assert saved_email_id.startswith("EML-")
        assert database.is_email_processed("purchasing", "facade-integration-message-1")

        due_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        task = database.schedule_communication_task(
            task_key="facade-integration-task-1",
            task_type="supplier_followup",
            mailbox="purchasing",
            recipient="facade-integration@example.test",
            subject="Follow up",
            body="Please confirm availability.",
            due_at=due_at.isoformat(),
        )
        due_tasks = database.list_due_communication_tasks(datetime.now(timezone.utc).isoformat())
        assert any(item["id"] == task["id"] for item in due_tasks)
        database.mark_communication_task_sent(task["id"])
        assert all(item["id"] != task["id"] for item in database.list_due_communication_tasks())
        assert database.list_dead_letter_tasks() == []
        with pytest.raises(RuntimeError, match="disabled for shared PostgreSQL"):
            database.reset_supplier_data()
    finally:
        sync_engine.dispose()


async def test_rfq_list_endpoint_reads_through_async_repository(disposable_postgres_engine):
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id="RFQ-ASYNC-API-1",
            customer_email="api-buyer@example.test",
            customer_name="Async API Buyer",
            raw_text="Need an asynchronously listed part",
        ).model_dump(mode="json"))
        session.add_all([
            OperationalRecord(
                domain="rfq_items",
                record_id="RFQ-ASYNC-ITEM-1",
                payload={
                    "id": "RFQ-ASYNC-ITEM-1", "rfq_id": "RFQ-ASYNC-API-1",
                    "requested_part_number": "ASYNC-PART-1", "quantity": 2,
                },
            ),
            OperationalRecord(
                domain="rfq_items",
                record_id="RFQ-OTHER-ITEM-1",
                payload={
                    "id": "RFQ-OTHER-ITEM-1", "rfq_id": "RFQ-OTHER-API-1",
                    "requested_part_number": "OTHER-PART", "quantity": 99,
                },
            ),
            OperationalRecord(
                domain="quotes",
                record_id="QUOTE-ASYNC-API-1",
                payload={
                    "id": "QUOTE-ASYNC-API-1", "rfq_id": "RFQ-ASYNC-API-1",
                    "subtotal": 100, "shipping_cost": 5, "total_amount": 105,
                    "status": "Draft",
                },
            ),
            OperationalRecord(
                domain="quotes",
                record_id="QUOTE-OTHER-API-1",
                payload={
                    "id": "QUOTE-OTHER-API-1", "rfq_id": "RFQ-OTHER-API-1",
                    "subtotal": 900, "shipping_cost": 5, "total_amount": 905,
                    "status": "Draft",
                },
            ),
            OperationalRecord(
                domain="quote_items",
                record_id="QUOTE-ASYNC-ITEM-1",
                payload={
                    "id": "QUOTE-ASYNC-ITEM-1", "quote_id": "QUOTE-ASYNC-API-1",
                    "rfq_item_id": "RFQ-ASYNC-ITEM-1", "part_number": "ASYNC-PART-1",
                    "quantity": 2, "unit_price": 50, "source": "Inventory",
                    "unit_cost": 40, "margin_percent": 20, "certificate_type": "CoC",
                },
            ),
            OperationalRecord(
                domain="quote_items",
                record_id="QUOTE-OTHER-ITEM-1",
                payload={
                    "id": "QUOTE-OTHER-ITEM-1", "quote_id": "QUOTE-OTHER-API-1",
                    "rfq_item_id": "RFQ-OTHER-ITEM-1", "part_number": "OTHER-PART",
                    "quantity": 99, "unit_price": 100,
                },
            ),
        ])

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {
        "email": "staff@example.test",
        "role": "ROLE_ADMIN",
    }
    app.dependency_overrides[get_async_db] = override_async_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/api/rfqs")
            detail_response = await client.get("/api/rfqs/RFQ-ASYNC-API-1")
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    assert response.status_code == 200
    assert any(record["id"] == "RFQ-ASYNC-API-1" for record in response.json())
    assert detail_response.status_code == 200
    assert detail_response.json()["rfq"]["id"] == "RFQ-ASYNC-API-1"
    assert [item["id"] for item in detail_response.json()["items"]] == ["RFQ-ASYNC-ITEM-1"]
    assert detail_response.json()["quote_details"]["quote"]["id"] == "QUOTE-ASYNC-API-1"
    assert [item["part_number"] for item in detail_response.json()["quote_details"]["items"]] == ["ASYNC-PART-1"]
    assert detail_response.json()["quote_details"]["items"][0]["quantity"] == 2


async def test_rfq_intake_endpoint_writes_through_async_repository(
    disposable_postgres_engine, monkeypatch
):
    from unittest.mock import Mock

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {
        "email": "staff@example.test",
        "role": "ROLE_ADMIN",
    }
    app.dependency_overrides[get_async_db] = override_async_db
    monkeypatch.setattr(
        "api.main.orchestration_service.process_rfq_pipeline",
        AsyncMock(return_value={"status": "Intake"}),
    )
    monkeypatch.setattr(
        "api.main.db_service.add_audit_log",
        Mock(side_effect=AssertionError("synchronous intake audit write used")),
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/rfqs/intake", json={
                "raw_text": "Part Number: ASYNC-TEST-1, Quantity: 1",
                "customer_name": "Async Intake Buyer",
                "customer_email": "async-intake@example.test",
            })
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    assert response.status_code == 200
    rfq_id = response.json()["rfq_id"]
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        record = await repositories.rfq.get(rfq_id)
        payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        audit_logs = await repositories.rfq.audit_logs(rfq_id)
    assert record is not None
    assert payload is not None
    assert payload["customer_email"] == "async-intake@example.test"
    assert len(audit_logs) == 1
    assert audit_logs[0].action_type == "intake_submission"


async def test_async_sales_mailbox_atomically_queues_new_rfq_and_deduplicates_moved_graph_id(
    disposable_postgres_engine, monkeypatch
):
    from unittest.mock import Mock

    from worker import _process_sales_message_async

    monkeypatch.setattr(
        "worker.classify_inbound_customer_message",
        lambda message, has_related_quote: {"category": "rfq"},
    )
    pipeline = AsyncMock(return_value={"status": "Pending_Internal_Review"})
    monkeypatch.setattr("worker.orchestration_service.process_rfq_pipeline", pipeline)
    monkeypatch.setattr(
        "worker.db_service.create_rfq",
        Mock(side_effect=AssertionError("synchronous RFQ creation used")),
    )

    message = {
        "message_id": "sales-mailbox-new-rfq-1",
        "internet_message_id": "<sales-mailbox-new-rfq-1@example.test>",
        "from": "New Buyer <new-buyer@example.test>",
        "subject": "Request for quotation",
        "body": "Please quote one verified test part.",
        "attachments": [],
    }
    assert await _process_sales_message_async(message, engine=disposable_postgres_engine) is True
    moved_message = {**message, "message_id": "sales-mailbox-moved-rfq-1"}
    assert await _process_sales_message_async(
        moved_message, engine=disposable_postgres_engine
    ) is True
    pipeline.assert_not_awaited()

    stable_key = inbound_dedupe_key(message["internet_message_id"])
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        rfqs = await repositories.rfq.list_operational_records("rfqs")
        buyer_rfqs = [
            record for record in rfqs.values()
            if record["customer_email"] == "new-buyer@example.test"
        ]
        assert len(buyer_rfqs) == 1
        rfq = buyer_rfqs[0]
        assert rfq["status"] == "Intake"
        assert "Please quote one verified test part." in rfq["raw_text"]

        events = await session.scalars(
            select(AutomationEventRecord).where(
                AutomationEventRecord.event_type == "process_new_rfq",
                AutomationEventRecord.entity_id == rfq["id"],
            )
        )
        assert len(list(events)) == 1
        claims = await session.scalars(
            select(InboundMessageIdempotencyRecord).where(
                InboundMessageIdempotencyRecord.message_id.in_(
                    [message["message_id"], stable_key]
                )
            )
        )
        claim_rows = list(claims)
        assert {record.message_id for record in claim_rows} == {
            message["message_id"], stable_key,
        }
        assert all(record.status == "processed" for record in claim_rows)
        archive = await session.scalar(
            select(RawEmailRecord).where(
                RawEmailRecord.provider_message_id == message["message_id"]
            )
        )
        assert archive is not None
        assert archive.processing_status == "processed"


async def test_postgres_automation_pause_persists_state_and_audit_together(disposable_postgres_engine):
    rfq_id = "RFQ-POSTGRES-AUTOMATION-1"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="pause-buyer@example.test",
            customer_name="Pause Buyer",
            raw_text="Need one test part",
        ).model_dump(mode="json"))
        result = await repositories.rfq.set_automation_paused(
            rfq_id, True, "Waiting for export-control review.", "operator@example.test"
        )
        assert result == {
            "rfq_id": rfq_id,
            "automation_paused": True,
            "pause_reason": "Waiting for export-control review.",
        }

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        audit_logs = await repositories.rfq.audit_logs(rfq_id)

    assert payload["automation_paused"] is True
    assert payload["pause_reason"] == "Waiting for export-control review."
    assert len(audit_logs) == 1
    assert audit_logs[0].action_type == "automation_pause"
    assert "operator@example.test" in audit_logs[0].message


async def test_postgres_shipment_event_updates_shipment_and_event_records(disposable_postgres_engine):
    from services.db_service import db_service

    shipment = Shipment(
        id="SHP-POSTGRES-EVENT-1",
        rfq_id="RFQ-POSTGRES-EVENT-1",
        customer_email="shipment-buyer@example.test",
        public_token="opaque-postgres-token",
        part_numbers=["TEST-PART-1"],
        quantity=1,
    )
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.records.upsert(
            "shipments", shipment.id, shipment.model_dump(mode="json")
        )
        event = await db_service.add_shipment_event_async(
            repositories,
            shipment.id,
            "Packed",
            "MIA warehouse",
            "Passed final inspection.",
        )
        assert event is not None

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        saved_shipment = await repositories.records.get("shipments", shipment.id)
        saved_events = await repositories.records.list_by_payload_value(
            "shipment_events", "shipment_id", shipment.id
        )

    assert saved_shipment["status"] == "Packed"
    assert saved_shipment["updated_at"] >= shipment.updated_at.isoformat()
    assert [payload["id"] for payload in saved_events.values()] == [event.id]
    assert saved_events[event.id]["description"] == "Passed final inspection."


async def test_postgres_shipment_creation_and_tracking_outbox_commit_together(
    disposable_postgres_engine,
):
    from api import main
    from models.operational_models import OutboxMessageRecord

    rfq_id = "RFQ-POSTGRES-SHIPMENT-CREATE"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="shipment-buyer@example.test",
            customer_name="Shipment Buyer",
            raw_text="Need one test part",
            status="Quote_Sent",
        ).model_dump(mode="json"))

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {
        "email": "operator@example.test", "role": "ROLE_ADMIN",
    }
    app.dependency_overrides[get_async_db] = override_async_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/internal/shipments", json={
                "rfq_id": rfq_id,
                "part_numbers": ["TEST-SHIPMENT-PART"],
                "quantity": 1,
            })
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        shipment = await repositories.records.get("shipments", response.json()["shipment_id"])
        events = await repositories.records.list_by_payload_value(
            "shipment_events", "shipment_id", response.json()["shipment_id"]
        )
        outbox_records = await session.scalars(
            select(OutboxMessageRecord).where(
                OutboxMessageRecord.entity_id == response.json()["shipment_id"]
            )
        )
        outbox = list(outbox_records)

    assert response.status_code == 200
    assert response.json()["tracking_notification"] == "PENDING"
    assert shipment["public_token"] in outbox[0].payload["body"]
    assert len(events) == 1
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"


async def test_postgres_human_po_approval_updates_rfq_po_and_audit_atomically(
    disposable_postgres_engine,
):
    from decimal import Decimal

    from api import main
    from models.async_models import PurchaseOrder
    from models.operational_models import OperationalRecord

    rfq_id = "RFQ-POSTGRES-PO-APPROVAL"
    quote_id = "QUOTE-POSTGRES-PO-APPROVAL"
    po_id = "PO-POSTGRES-PO-APPROVAL"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="po-buyer@example.test",
            customer_name="PO Buyer",
            raw_text="Need one test part",
            status="Pending_PO_Review",
        ).model_dump(mode="json"))
        await repositories.quote.create(id=quote_id, rfq_id=rfq_id, total_amount=25.0)
        session.add(OperationalRecord(
            domain="quotes",
            record_id=quote_id,
            payload={"id": quote_id, "rfq_id": rfq_id, "status": "Sent", "version": 1},
        ))
        session.add(PurchaseOrder(
            id=po_id,
            po_number="PO-POSTGRES-APPROVAL-1",
            customer_email="po-buyer@example.test",
            total_amount=Decimal("25.00"),
            status="Pending_PO_Review",
            quote_id=quote_id,
            rfq_id=rfq_id,
            attachment_metadata=[],
        ))

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {"email": "operator@example.test", "role": "ROLE_ADMIN"}
    app.dependency_overrides[get_async_db] = override_async_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/api/purchase-orders/{quote_id}/approve",
                json={"operator_name": "Test Operator", "comments": "Documents verified."},
            )
            duplicate_response = await client.post(
                f"/api/purchase-orders/{quote_id}/approve",
                json={"operator_name": "Test Operator", "comments": "Duplicate approval."},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        rfq_payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        purchase_order = await session.get(PurchaseOrder, po_id)
        audit_logs = await repositories.rfq.audit_logs(rfq_id)

    assert response.status_code == 200
    assert duplicate_response.status_code == 409
    assert rfq_payload["status"] == "Purchase_Order_Received"
    assert purchase_order.status == "Purchase_Order_Received"
    assert len(audit_logs) == 1
    assert audit_logs[0].action_type == "purchase_order_approved"


async def test_postgres_quote_approval_queues_email_and_followups_atomically(
    disposable_postgres_engine, monkeypatch,
):
    from api import main
    from agents.base_agent import AgentResponse
    from models.operational_models import (
        AutomationEventRecord,
        CommunicationTaskRecord,
        CustomerQuoteItemRecord,
        CustomerQuoteRecord,
        LLMTelemetryRecord,
        OperationalRecord,
        OutboxMessageRecord,
            QuoteItemRecord,
    )

    rfq_id = "RFQ-POSTGRES-QUOTE-APPROVAL"
    quote_id = "QTE-1014"
    item_id = "QITEM-POSTGRES-QUOTE-APPROVAL"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="approval-buyer@example.test",
            customer_name="Approval Buyer",
            raw_text="Need one verified test part",
            thread_id="thread-quote-approval",
            status="Pending_Approval",
        ).model_dump(mode="json"))
        await repositories.quote.create(
            id=quote_id, rfq_id=rfq_id, total_amount=55.0, status="Pending_Approval"
        )
        session.add(OperationalRecord(
            domain="quotes",
            record_id=quote_id,
            payload={
                "id": quote_id, "rfq_id": rfq_id, "status": "Pending_Approval",
                "subtotal": 50.0, "shipping_cost": 5.0, "total_amount": 55.0,
                "version": 1,
            },
        ))
        item_payload = {
            "id": item_id, "quote_id": quote_id, "rfq_item_id": "RFQ-ITEM-1",
            "part_number": "APPROVAL-PART-1", "description": "Test part",
            "quantity": 1, "uom": "EA", "unit_price": 50.0, "unit_cost": 35.0,
            "margin_percent": 30.0, "certificate_type": "CoC", "attachments": [],
        }
        session.add(OperationalRecord(
            domain="quote_items", record_id=item_id, payload=item_payload,
        ))
        session.add(QuoteItemRecord(
            id=item_id, quote_id=quote_id, part_number="APPROVAL-PART-1",
            quantity=1, unit_price=50.0, details=item_payload,
        ))
        session.add(CustomerQuoteRecord(
            id=quote_id, rfq_id=rfq_id, quote_number=quote_id, unit_price=50.0,
            quantity=1, total_price=55.0, currency="USD", status="Pending_Approval",
        ))
        session.add(CustomerQuoteItemRecord(
            id=item_id, quote_id=quote_id, rfq_item_id="RFQ-ITEM-1",
            part_number="APPROVAL-PART-1", description="Test part", quantity=1,
            condition="NE", certification="CoC", unit_price=50.0,
        ))

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {
        "email": "operator@example.test", "role": "ROLE_ADMIN",
    }
    app.dependency_overrides[get_async_db] = override_async_db
    monkeypatch.setattr(main.orchestration_service.comm_agent, "execute", AsyncMock(return_value=AgentResponse(
        success=True,
        data={
            "formatted_body": "Your approved quote QTE-1014 is ready.",
            "subject": "Quotation QTE-1014",
            "telemetry": {
                "task": "customer_communication", "prompt_version": "test-v1",
                "model_id": "template-fallback", "model_calls": [],
                "latency_ms": 1, "input_tokens": 0, "output_tokens": 0,
                "estimated_cost_usd": 0, "validation_result": "TEMPLATE_FALLBACK",
            },
            "automation_event": {
                "event_type": "llm_email_draft", "entity_type": "quote",
                "entity_id": quote_id, "status": "FALLBACK", "result": "{}",
            },
            "llm_fallback_used": True,
        },
    )))
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(f"/api/quotes/{quote_id}/approve", json={
                "operator_name": "Test Operator",
                "comments": "Margin checked.",
                "expected_version": 1,
                "items_override": [{"quote_item_id": item_id, "unit_price": 60.0}],
            })
            duplicate_response = await client.post(f"/api/quotes/{quote_id}/approve", json={
                "operator_name": "Test Operator", "expected_version": 1,
            })
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        quote_payload = await repositories.records.get("quotes", quote_id)
        saved_item = await repositories.records.get("quote_items", item_id)
        customer_quote = await session.get(CustomerQuoteRecord, quote_id)
        customer_item = await session.get(CustomerQuoteItemRecord, item_id)
        telemetry = await session.scalars(
            select(LLMTelemetryRecord).where(LLMTelemetryRecord.task == "customer_communication")
        )
        automation_events = await session.scalars(
            select(AutomationEventRecord).where(AutomationEventRecord.entity_id == quote_id)
        )
        followups = await session.scalars(
            select(CommunicationTaskRecord).where(CommunicationTaskRecord.task_type == "customer_followup")
        )
        outbox = await session.scalars(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        )
        audit_logs = await repositories.rfq.audit_logs(rfq_id)
        telemetry_rows = list(telemetry)
        event_rows = list(automation_events)
        followup_rows = list(followups)
        outbox_rows = list(outbox)

    assert response.status_code == 200
    assert response.json()["status"] == "Quote_Dispatch_Pending"
    assert duplicate_response.status_code == 409
    assert quote_payload["status"] == "Approved"
    assert quote_payload["approved_by"] == "Test Operator"
    assert quote_payload["version"] == 2
    assert quote_payload["total_amount"] == 65.0
    assert saved_item["unit_price"] == 60.0
    assert customer_quote.status == "Approved"
    assert customer_quote.total_price == 65.0
    assert customer_item.unit_price == 60.0
    assert len(telemetry_rows) == 1
    assert len(event_rows) == 1
    assert len(followup_rows) == 3
    assert len(outbox_rows) == 1
    assert outbox_rows[0].status == "PENDING"
    assert [log.action_type for log in audit_logs] == ["human_override", "human_approval"]


async def test_postgres_po_submission_and_notification_outbox_commit_together(
    disposable_postgres_engine, monkeypatch,
):
    from models.async_models import PurchaseOrder
    from models.operational_models import OperationalRecord, OutboxMessageRecord
    from api import main

    rfq_id = "RFQ-POSTGRES-PO-SUBMISSION-API"
    quote_id = "QTE-1011"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="po-buyer@example.test",
            customer_name="PO Buyer",
            raw_text="Need one test part",
            status="Quote_Sent",
        ).model_dump(mode="json"))
        await repositories.quote.create(id=quote_id, rfq_id=rfq_id, total_amount=25.0)
        session.add(OperationalRecord(
            domain="quotes",
            record_id=quote_id,
            payload={"id": quote_id, "rfq_id": rfq_id, "total_amount": 25.0, "status": "Sent"},
        ))
        session.add(OperationalRecord(
            domain="quote_items",
            record_id="QITEM-POSTGRES-PO-1",
            payload={
                "id": "QITEM-POSTGRES-PO-1", "quote_id": quote_id,
                "part_number": "TEST-PART-PO-1", "quantity": 1,
                "unit_price": 25.0, "unit_cost": 15.0,
            },
        ))

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {
        "email": "po-buyer@example.test", "role": "ROLE_CUSTOMER",
    }
    app.dependency_overrides[get_async_db] = override_async_db
    monkeypatch.setenv("CAMILA_NOTIFICATION_EMAIL", "review@example.test")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post("/api/purchase-orders", json={
                "quote_id": quote_id,
                "po_number": "PO-1011",
                "attachment_ids": ["ATT-PO-1", "ATT-PO-2", "ATT-PO-3"],
            })
            duplicate_response = await client.post("/api/purchase-orders", json={
                "quote_id": quote_id,
                "po_number": "PO-1011",
                "attachment_ids": ["ATT-PO-1", "ATT-PO-2", "ATT-PO-3"],
            })
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        rfq_payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        purchase_orders = await session.scalars(
            select(PurchaseOrder).where(PurchaseOrder.quote_id == quote_id)
        )
        outbox_records = await session.scalars(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        )
        audit_logs = await repositories.rfq.audit_logs(rfq_id)
        purchase_order = next(iter(purchase_orders), None)
        outbox = list(outbox_records)

    assert response.status_code == 200
    assert response.json()["internal_notification"]["transmission_status"] == "PENDING"
    assert duplicate_response.status_code == 409
    assert rfq_payload["status"] == "Pending_PO_Review"
    assert purchase_order is not None
    assert purchase_order.status == "Pending_PO_Review"
    assert len(outbox) == 1
    assert outbox[0].status == "PENDING"
    assert len(audit_logs) == 1
    assert audit_logs[0].action_type == "purchase_order_received"


async def test_postgres_quote_rejection_updates_customer_quote_and_audit_atomically(
    disposable_postgres_engine,
):
    from api import main
    from models.operational_models import CustomerQuoteRecord, OperationalRecord

    rfq_id = "RFQ-POSTGRES-QUOTE-REJECTION"
    quote_id = "QUOTE-POSTGRES-QUOTE-REJECTION"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="quote-buyer@example.test",
            customer_name="Quote Buyer",
            raw_text="Need one test part",
            status="Quote_Sent",
        ).model_dump(mode="json"))
        await repositories.quote.create(id=quote_id, rfq_id=rfq_id, total_amount=25.0)
        session.add(OperationalRecord(
            domain="quotes",
            record_id=quote_id,
            payload={"id": quote_id, "rfq_id": rfq_id, "status": "Sent", "version": 1},
        ))
        session.add(CustomerQuoteRecord(
            id=quote_id,
            rfq_id=rfq_id,
            quote_number="QT-POSTGRES-REJECTION-1",
            unit_price=25.0,
            quantity=1,
            total_price=25.0,
            currency="USD",
            status="Sent",
        ))

    async def override_async_db():
        async with session_scope(disposable_postgres_engine) as session:
            yield session

    app.dependency_overrides[current_user] = lambda: {"email": "operator@example.test", "role": "ROLE_ADMIN"}
    app.dependency_overrides[get_async_db] = override_async_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                f"/api/quotes/{quote_id}/reject",
                json={"operator_name": "Test Operator", "comments": "Pricing not accepted."},
            )
            duplicate_response = await client.post(
                f"/api/quotes/{quote_id}/reject",
                json={"operator_name": "Test Operator", "comments": "Duplicate rejection."},
            )
    finally:
        app.dependency_overrides.pop(current_user, None)
        app.dependency_overrides.pop(get_async_db, None)

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        quote_payload = await repositories.records.get("quotes", quote_id)
        rfq_payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        customer_quote = await session.get(CustomerQuoteRecord, quote_id)
        audit_logs = await repositories.rfq.audit_logs(rfq_id)

    assert response.status_code == 200
    assert duplicate_response.status_code == 409
    assert quote_payload["status"] == "Rejected"
    assert quote_payload["approved_by"] == "Test Operator"
    assert quote_payload["approved_at"]
    assert rfq_payload["status"] == "Rejected"
    assert customer_quote.status == "Rejected"
    assert len(audit_logs) == 1
    assert audit_logs[0].action_type == "human_rejection"


async def test_postgres_async_outbox_enqueue_is_idempotent(disposable_postgres_engine):
    from models.operational_models import OutboxMessageRecord

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        first = await repositories.records.enqueue_outbox_message(
            deduplication_key="async-outbox-idempotency-test",
            mailbox="sales",
            recipient="buyer@example.test",
            subject="Test quote notification",
            body="First body",
            entity_id="QUOTE-ASYNC-OUTBOX",
        )
        duplicate = await repositories.records.enqueue_outbox_message(
            deduplication_key="async-outbox-idempotency-test",
            mailbox="sales",
            recipient="buyer@example.test",
            subject="Test quote notification",
            body="Duplicate body must not replace the original",
            entity_id="QUOTE-ASYNC-OUTBOX",
        )
        assert first["id"] == duplicate["id"]
        assert first["status"] == duplicate["status"] == "PENDING"
        assert duplicate["retry_count"] == 0

    async with session_scope(disposable_postgres_engine) as session:
        rows = await session.scalars(
            select(OutboxMessageRecord).where(
                OutboxMessageRecord.deduplication_key == "async-outbox-idempotency-test"
            )
        )
        saved = list(rows)

    assert len(saved) == 1
    assert saved[0].payload == {"body": "First body"}


async def test_postgres_outbox_retry_and_stale_delivery_recovery(disposable_postgres_engine):
    from sqlalchemy import update

    async with disposable_postgres_engine.connect() as connection:
        schema_name = await connection.scalar(text("SELECT current_schema()"))
    sync_url = disposable_postgres_engine.url.set(
        drivername="postgresql+psycopg2"
    ).update_query_dict({"options": f"-csearch_path={schema_name}"})
    sync_engine = create_engine(sync_url, pool_size=4, max_overflow=0)
    repository = PostgresReviewTelemetryRepository(engine=sync_engine)
    try:
        retryable_message = repository.enqueue_outbox_message(
            deduplication_key="pg-outbox-retry-recovery",
            mailbox="sales",
            recipient="buyer@example.test",
            subject="Retry delivery",
            body="Retryable delivery test",
        )
        claimed = repository.claim_outbox_messages(limit=1)
        assert [message["id"] for message in claimed] == [retryable_message["id"]]
        assert claimed[0]["retry_count"] == 1
        assert repository.fail_outbox_message(
            retryable_message["id"], "Temporary mail-service failure", retryable=True
        ) == "PENDING"

        with sync_engine.begin() as connection:
            connection.execute(text(
                "UPDATE outbox_messages SET available_at = now() WHERE id = :id"
            ), {"id": retryable_message["id"]})
        retried = repository.claim_outbox_messages(limit=1)
        assert len(retried) == 1
        assert retried[0]["id"] == retryable_message["id"]
        assert retried[0]["retry_count"] == 2
        assert repository.fail_outbox_message(
            retryable_message["id"], "Unknown external delivery outcome", retryable=False
        ) == "MANUAL_REVIEW_REQUIRED"

        stale_message = repository.enqueue_outbox_message(
            deduplication_key="pg-outbox-stale-recovery",
            mailbox="sales",
            recipient="buyer@example.test",
            subject="Stale delivery",
            body="Unknown outcome recovery test",
        )
        stale_claim = repository.claim_outbox_messages(limit=1)
        assert stale_claim[0]["id"] == stale_message["id"]
        with sync_engine.begin() as connection:
            connection.execute(text(
                "UPDATE outbox_messages SET sending_started_at = now() - interval '10 minutes' "
                "WHERE id = :id"
            ), {"id": stale_message["id"]})
        assert repository.recover_stale_outbox_messages(sending_timeout_seconds=60) == 1

        with sync_engine.connect() as connection:
            statuses = connection.execute(text(
                "SELECT id, status FROM outbox_messages WHERE id IN (:retry_id, :stale_id)"
            ), {"retry_id": retryable_message["id"], "stale_id": stale_message["id"]}).mappings().all()
        assert {row["id"]: row["status"] for row in statuses} == {
            retryable_message["id"]: "MANUAL_REVIEW_REQUIRED",
            stale_message["id"]: "MANUAL_REVIEW_REQUIRED",
        }
    finally:
        sync_engine.dispose()


async def test_postgres_outbox_worker_retries_then_finalizes_once(
    disposable_postgres_engine, monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from repositories.review_telemetry_repository import PostgresReviewTelemetryRepository
    from services.communication_service import CommunicationService

    async with disposable_postgres_engine.connect() as connection:
        schema_name = await connection.scalar(text("SELECT current_schema()"))
    sync_url = disposable_postgres_engine.url.set(
        drivername="postgresql+psycopg2"
    ).update_query_dict({"options": f"-csearch_path={schema_name}"})
    sync_engine = create_engine(sync_url, pool_size=4, max_overflow=0)
    repository = PostgresReviewTelemetryRepository(engine=sync_engine)
    try:
        queued = repository.enqueue_outbox_message(
            deduplication_key="pg-outbox-worker-replay",
            mailbox="sales",
            recipient="buyer@example.test",
            subject="Replay test",
            body="Retry then deliver once",
        )

        class StoreProxy:
            storage_engine = "postgresql"

            def __getattr__(self, name):
                return getattr(repository, name)

        monkeypatch.setattr("services.communication_service.operations_store", StoreProxy())
        send_message = Mock(side_effect=[
            type("HttpError", (Exception,), {"response": SimpleNamespace(status_code=503)})(),
            None,
        ])
        monkeypatch.setattr("services.communication_service.send_message", send_message)
        communication = CommunicationService()

        assert communication.dispatch_outbox_once() == {"sent": 0, "failed": 1}
        with sync_engine.begin() as connection:
            connection.execute(text(
                "UPDATE outbox_messages SET available_at = now() WHERE id = :id"
            ), {"id": queued["id"]})
        assert communication.dispatch_outbox_once() == {"sent": 1, "failed": 0}
        assert communication.dispatch_outbox_once() == {"sent": 0, "failed": 0}
        assert send_message.call_count == 2

        with sync_engine.connect() as connection:
            outbox_status = connection.execute(text(
                "SELECT status, retry_count FROM outbox_messages WHERE id = :id"
            ), {"id": queued["id"]}).mappings().one()
            communication_count = connection.execute(text(
                "SELECT count(*) FROM communications WHERE entity_id = :id"
            ), {"id": queued["id"]}).scalar_one()
        assert outbox_status["status"] == "SENT"
        assert outbox_status["retry_count"] == 2
        assert communication_count == 1
    finally:
        sync_engine.dispose()


async def test_postgres_async_outbox_dispatch_finalizes_quote_after_delivery(
    disposable_postgres_engine, monkeypatch,
):
    from unittest.mock import Mock

    from models.operational_models import (
        CommunicationRecord,
        CustomerQuoteRecord,
        OperationalRecord,
        OutboxMessageRecord,
    )
    from services.communication_service import CommunicationService

    rfq_id = "RFQ-POSTGRES-ASYNC-OUTBOX-FINALIZE"
    quote_id = "QTE-POSTGRES-ASYNC-OUTBOX-FINALIZE"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="delivery-buyer@example.test",
            customer_name="Delivery Buyer",
            raw_text="Need one delivered quote",
            status="Pending_Approval",
        ).model_dump(mode="json"))
        await repositories.quote.create(
            id=quote_id, rfq_id=rfq_id, total_amount=25.0, status="Approved"
        )
        session.add(OperationalRecord(
            domain="quotes",
            record_id=quote_id,
            payload={"id": quote_id, "rfq_id": rfq_id, "status": "Approved", "version": 2},
        ))
        session.add(CustomerQuoteRecord(
            id=quote_id, rfq_id=rfq_id, quote_number=quote_id,
            unit_price=25.0, quantity=1, total_price=25.0, currency="USD", status="Approved",
        ))
        await repositories.records.enqueue_outbox_message(
            deduplication_key=f"customer-quote:{quote_id}",
            mailbox="sales",
            recipient="delivery-buyer@example.test",
            subject="Quotation",
            body="Approved quote",
            entity_id=quote_id,
        )

    send_message = Mock(return_value=None)
    monkeypatch.setattr("services.communication_service.send_message", send_message)
    communication = CommunicationService()
    assert await communication.dispatch_outbox_once_async(disposable_postgres_engine) == {
        "sent": 1, "failed": 0,
    }
    assert await communication.dispatch_outbox_once_async(disposable_postgres_engine) == {
        "sent": 0, "failed": 0,
    }
    assert send_message.call_count == 1

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        quote = await repositories.records.get("quotes", quote_id)
        rfq = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        customer_quote = await session.get(CustomerQuoteRecord, quote_id)
        communications = await session.scalars(
            select(CommunicationRecord).where(CommunicationRecord.entity_type == "email")
        )
        outbox = await session.scalars(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        )

    assert quote["status"] == "Sent"
    assert rfq["status"] == "Quote_Sent"
    assert customer_quote.status == "Sent"
    assert len(list(communications)) == 1
    assert len(list(outbox)) == 1


async def test_postgres_async_outbox_timeout_requires_manual_review(
    disposable_postgres_engine, monkeypatch,
):
    from unittest.mock import Mock

    from models.operational_models import (
        CommunicationTaskRecord,
        CustomerQuoteRecord,
        OperationalRecord,
        OutboxMessageRecord,
    )
    from services.communication_service import CommunicationService

    rfq_id = "RFQ-POSTGRES-ASYNC-OUTBOX-AMBIGUOUS"
    quote_id = "QTE-POSTGRES-ASYNC-OUTBOX-AMBIGUOUS"
    task_id = "TASK-POSTGRES-ASYNC-OUTBOX-AMBIGUOUS"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        await repositories.rfq.create_from_payload(RFQ(
            id=rfq_id,
            customer_email="ambiguous-buyer@example.test",
            customer_name="Ambiguous Buyer",
            raw_text="Need one quote",
            status="Quote_Dispatch_Pending",
        ).model_dump(mode="json"))
        await repositories.quote.create(
            id=quote_id, rfq_id=rfq_id, total_amount=25.0, status="Approved"
        )
        session.add(OperationalRecord(
            domain="quotes", record_id=quote_id,
            payload={"id": quote_id, "rfq_id": rfq_id, "status": "Approved", "version": 1},
        ))
        session.add(CustomerQuoteRecord(
            id=quote_id, rfq_id=rfq_id, quote_number=quote_id,
            unit_price=25.0, quantity=1, total_price=25.0, currency="USD", status="Approved",
        ))
        session.add(CommunicationTaskRecord(
            id=task_id, task_key=f"customer-followup:{quote_id}",
            recipient="ambiguous-buyer@example.test", subject="Follow up", body="Follow up",
            task_type="customer_followup", mailbox="sales", status="pending", attempts=0,
            max_attempts=5, due_at=datetime.now(timezone.utc) + timedelta(days=1),
        ))
        await repositories.records.enqueue_outbox_message(
            deduplication_key=f"customer-quote:{quote_id}",
            mailbox="sales", recipient="ambiguous-buyer@example.test",
            subject="Quotation", body="Approved quote", entity_id=quote_id,
        )

    monkeypatch.setattr(
        "services.communication_service.send_message",
        Mock(side_effect=TimeoutError("delivery outcome unknown")),
    )
    result = await CommunicationService().dispatch_outbox_once_async(disposable_postgres_engine)
    assert result == {"sent": 0, "failed": 1}

    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        quote = await repositories.records.get("quotes", quote_id)
        rfq = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        customer_quote = await session.get(CustomerQuoteRecord, quote_id)
        followup = await session.get(CommunicationTaskRecord, task_id)
        outbox = await session.scalar(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        )

    assert quote["status"] == "Pending_Internal_Review"
    assert rfq["status"] == "Pending_Internal_Review"
    assert customer_quote.status == "Pending_Internal_Review"
    assert followup.status == "cancelled"
    assert outbox.status == "MANUAL_REVIEW_REQUIRED"


async def test_postgres_async_scheduled_task_queues_outbox_idempotently(
    disposable_postgres_engine,
):
    from models.operational_models import CommunicationTaskRecord, OutboxMessageRecord
    from worker import queue_due_communication_tasks

    task_id = "TASK-POSTGRES-ASYNC-SCHEDULED-1"
    task_key = "customer-followup:QTE-POSTGRES-ASYNC-SCHEDULED"
    async with session_scope(disposable_postgres_engine) as session:
        session.add(CommunicationTaskRecord(
            id=task_id,
            task_key=task_key,
            recipient="buyer@example.test",
            subject="Scheduled quote follow-up",
            body="Following up on your quote.",
            task_type="customer_followup",
            mailbox="sales",
            status="pending",
            attempts=0,
            max_attempts=5,
            due_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))

    first = await queue_due_communication_tasks(disposable_postgres_engine)
    duplicate = await queue_due_communication_tasks(disposable_postgres_engine)
    assert first == duplicate == {"queued": 1, "failed": 0}

    async with session_scope(disposable_postgres_engine) as session:
        records = await session.scalars(
            select(OutboxMessageRecord).where(
                OutboxMessageRecord.communication_task_id == task_id
            )
        )
        outbox_rows = list(records)

    assert len(outbox_rows) == 1
    assert outbox_rows[0].status == "PENDING"
    assert outbox_rows[0].payload == {"body": "Following up on your quote."}


async def test_postgres_async_inventory_attachment_import_persists_offer_and_row_audit(
    disposable_postgres_engine,
):
    from services.supplier_inventory_importer import import_inventory_attachments_async
    from models.operational_models import SupplierInventoryImportRecord, SupplierInventoryRowRecord, SupplierPartRecord

    message = {
        "message_id": "MSG-ASYNC-INVENTORY-1",
        "internet_message_id": "<inventory-async-1@example.test>",
        "from": "Supplier Contact <supplier@example.test>",
        "subject": "Inventory CSV",
        "body": "Please see attached inventory.",
        "attachments": [{
            "filename": "inventory.csv",
            "content_type": "text/csv",
            "content": b"Part Number,Quantity,Condition,Price,Currency,Lead Time,Certificate\nPN-ASYNC-1,3,NE,42.50,USD,4,CoC\n",
        }],
    }
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        result = await import_inventory_attachments_async(message, "purchasing", repositories)

    async with session_scope(disposable_postgres_engine) as session:
        imports = await session.scalars(
            select(SupplierInventoryImportRecord).where(
                SupplierInventoryImportRecord.source_message_id == "<inventory-async-1@example.test>"
            )
        )
        rows = await session.scalars(select(SupplierInventoryRowRecord))
        offers = await session.scalars(
            select(SupplierPartRecord).where(SupplierPartRecord.source_email_id.like("<inventory-async-1@example.test>:%"))
        )
        saved_imports = list(imports)
        saved_rows = list(rows)
        saved_offers = list(offers)

    assert result["status"] == "Inventory_Table_Imported"
    assert result["part_numbers"] == ["PN-ASYNC-1"]
    assert len(saved_imports) == 1
    assert saved_imports[0].rows_imported == 1
    assert len(saved_rows) == 1
    assert saved_rows[0].part_number == "PN-ASYNC-1"
    assert saved_rows[0].status == "imported"
    assert len(saved_offers) == 1
    assert saved_offers[0].quantity_available == 3
    assert saved_offers[0].unit_cost == 42.5


async def test_postgres_inventory_worker_uses_async_attachment_transaction(
    disposable_postgres_engine, monkeypatch,
):
    from services.inventory_ingestion_worker import InventoryIngestionWorker
    from models.operational_models import (
        InboundMessageIdempotencyRecord,
        RawEmailRecord,
        SupplierInventoryImportRecord,
        SupplierInventoryRowRecord,
        SupplierPartRecord,
    )

    worker = InventoryIngestionWorker(fetch_messages=lambda _mailbox, limit: [])
    worker.postgres_enabled = True
    monkeypatch.setenv("USE_ASYNC_REPOS", "true")
    monkeypatch.setattr(
        "services.inventory_ingestion_worker.create_engine_from_environment",
        lambda: disposable_postgres_engine,
    )
    monkeypatch.setattr(worker, "_enqueue_waiting_rfqs", lambda _part_number: None)
    message = {
        "message_id": "MSG-ASYNC-INV-WORKER-1",
        "internet_message_id": "<inv-worker-1@example.test>",
        "conversation_id": "conversation-inv-1",
        "from": "Supplier Contact <worker-supplier@example.test>",
        "subject": "Inventory CSV",
        "body": "Please see attached inventory.",
        "attachments": [{
            "filename": "inventory.csv",
            "content_type": "text/csv",
            "content": b"Part Number,Quantity,Condition,Price,Currency,Lead Time,Certificate\nPN-WORKER-1,4,NE,52.00,USD,5,CoC\n",
        }],
    }

    first = await worker._process_inventory_table_message_async(
        message, engine=disposable_postgres_engine
    )
    duplicate = await worker._process_inventory_table_message_async(
        message, engine=disposable_postgres_engine
    )

    async with session_scope(disposable_postgres_engine) as session:
        imports = await session.scalars(
            select(SupplierInventoryImportRecord).where(
                SupplierInventoryImportRecord.source_message_id == "<inv-worker-1@example.test>"
            )
        )
        rows = await session.scalars(select(SupplierInventoryRowRecord))
        offers = await session.scalars(
            select(SupplierPartRecord).where(SupplierPartRecord.source_email_id.like("<inv-worker-1@example.test>:%"))
        )
        inbound = await session.get(InboundMessageIdempotencyRecord, "MSG-ASYNC-INV-WORKER-1")
        archived = await session.scalars(
            select(RawEmailRecord).where(RawEmailRecord.provider_message_id == "MSG-ASYNC-INV-WORKER-1")
        )
        saved_imports = list(imports)
        saved_rows = list(rows)
        saved_offers = list(offers)
        saved_archives = list(archived)

    assert first["success"] is True
    assert first["result"]["part_numbers"] == ["PN-WORKER-1"]
    assert duplicate["skipped"] is True
    assert inbound.status == "processed"
    assert len(saved_archives) == len(saved_imports) == len(saved_rows) == len(saved_offers) == 1


async def test_postgres_plain_supplier_email_worker_uses_async_persistence(
    disposable_postgres_engine, monkeypatch,
):
    from models.operational_models import InboundEmailRecord, InboundMessageIdempotencyRecord, RawEmailRecord, SupplierPartRecord
    from services.inventory_ingestion_worker import InventoryIngestionWorker

    worker = InventoryIngestionWorker(fetch_messages=lambda _mailbox, limit: [])
    monkeypatch.setenv("LLM_LIVE_ENABLED", "false")
    message = {
        "message_id": "MSG-ASYNC-SUPPLIER-PLAIN-1",
        "internet_message_id": "<plain-supplier-1@example.test>",
        "from": "Supplier Contact <plain-supplier@example.test>",
        "subject": "Quote for P/N PN-PLAIN-1",
        "body": "Part Number: PN-PLAIN-1\nQuantity available: 3\nUnit price: $42.50\nCondition: NE\nFAA 8130-3 included.\nLead time: 4 days",
        "attachments": [],
    }
    result = await worker._process_plain_supplier_message_async(
        message, engine=disposable_postgres_engine
    )

    async with session_scope(disposable_postgres_engine) as session:
        inbound = await session.get(
            InboundMessageIdempotencyRecord, "MSG-ASYNC-SUPPLIER-PLAIN-1"
        )
        raw_email = await session.scalar(
            select(RawEmailRecord).where(
                RawEmailRecord.provider_message_id == "MSG-ASYNC-SUPPLIER-PLAIN-1"
            )
        )
        parsed_email = await session.scalar(
            select(InboundEmailRecord).where(
                InboundEmailRecord.message_id == "MSG-ASYNC-SUPPLIER-PLAIN-1"
            )
        )
        offers = await session.scalars(
            select(SupplierPartRecord).where(
                SupplierPartRecord.source_email_id == "MSG-ASYNC-SUPPLIER-PLAIN-1"
            )
        )
        saved_offers = list(offers)

    assert result["success"] is True
    assert result["result"]["part_number"] == "PN-PLAIN-1"
    assert inbound.status == "processed"
    assert raw_email is not None
    assert parsed_email is not None
    assert len(saved_offers) == 1


async def test_postgres_async_unreadable_supplier_pdf_queues_same_thread_clarification(
    disposable_postgres_engine, monkeypatch,
):
    from models.operational_models import InboundEmailRecord, InboundMessageIdempotencyRecord, OutboxMessageRecord
    from services.inventory_ingestion_worker import InventoryIngestionWorker

    worker = InventoryIngestionWorker(fetch_messages=lambda _mailbox, limit: [])
    monkeypatch.setenv("LLM_LIVE_ENABLED", "false")
    message = {
        "message_id": "MSG-ASYNC-SUPPLIER-PDF-1",
        "internet_message_id": "<unreadable-supplier-pdf-1@example.test>",
        "from": "Supplier Contact <unreadable-pdf@example.test>",
        "subject": "Supplier quotation attachment",
        "body": "Please see the attached quotation.",
        "attachments": [{
            "filename": "quote.pdf",
            "content_type": "application/pdf",
            "content": b"not a readable PDF",
        }],
    }
    result = await worker._process_plain_supplier_message_async(
        message, engine=disposable_postgres_engine
    )

    async with session_scope(disposable_postgres_engine) as session:
        inbound = await session.get(
            InboundMessageIdempotencyRecord, "MSG-ASYNC-SUPPLIER-PDF-1"
        )
        archived_email = await session.scalar(
            select(InboundEmailRecord).where(
                InboundEmailRecord.message_id == "MSG-ASYNC-SUPPLIER-PDF-1"
            )
        )
        outbox = await session.scalar(
            select(OutboxMessageRecord).where(
                OutboxMessageRecord.recipient == "unreadable-pdf@example.test",
                OutboxMessageRecord.reply_to == "MSG-ASYNC-SUPPLIER-PDF-1",
            )
        )

    assert result["success"] is False
    assert result["result"]["status"] == "Unreadable_PDF_Clarification_Sent"
    assert inbound.status == "processed"
    assert archived_email.processing_status == "clarification_sent"
    assert outbox is not None
    assert outbox.mailbox == "purchasing"
    assert "Part number" in outbox.payload["body"]


async def test_postgres_async_supplier_negotiation_persists_state_and_counteroffer(
    disposable_postgres_engine, monkeypatch,
):
    from models.operational_models import CommunicationTaskRecord, NegotiationSessionRecord
    from services.negotiation_service import SupplierNegotiationService

    monkeypatch.setenv("NEGOTIATION_MIN_LINE_VALUE", "500")
    monkeypatch.setenv("SUPPLIER_DISCOUNT_MAX_ROUNDS", "2")
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        service = SupplierNegotiationService()
        result = await service.record_supplier_quote_async(
            repositories,
            supplier_email="negotiation-supplier@example.test",
            supplier_name="Negotiation Supplier",
            part_number="NEGOTIATION-PART-1",
            quantity=10,
            unit_cost=100.0,
            source_email_id="MSG-NEGOTIATION-1",
            reply_to="thread-negotiation-1",
        )
        assert result["status"] == "COUNTEROFFER_SENT"

    async with session_scope(disposable_postgres_engine) as session:
        negotiation = await session.scalar(
            select(NegotiationSessionRecord).where(
                NegotiationSessionRecord.supplier_email == "negotiation-supplier@example.test",
                NegotiationSessionRecord.part_number == "NEGOTIATION-PART-1",
            )
        )
        task = await session.scalar(
            select(CommunicationTaskRecord).where(
                CommunicationTaskRecord.task_key == "supplier-discount:"
                + result["session_id"] + ":1"
            )
        )

    assert negotiation is not None
    assert negotiation.payload["session"]["state"] == "COUNTEROFFER_SENT"
    assert task is not None
    assert task.task_type == "supplier_discount_request"
    assert task.mailbox == "purchasing"
    assert task.reply_to == "thread-negotiation-1"


async def test_postgres_async_customer_question_queues_grounded_reply_once(
    disposable_postgres_engine, monkeypatch,
):
    from models.db_models import Quote, QuoteItem, RFQ
    from models.operational_models import (
        AuditLogRecord,
        CommunicationTaskRecord,
        InboundMessageIdempotencyRecord,
        OutboxMessageRecord,
        RawEmailRecord,
    )
    from services.customer_chase_schedule import chase_task_keys
    from services.communication_service import communication_service, customer_question_service
    from worker import _process_sales_message_async

    rfq_id = "RFQ-ASYNC-CUSTOMER-QUESTION"
    quote_id = "QTE-ASYNC-CUSTOMER-QUESTION"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        rfq = RFQ(
            id=rfq_id,
            customer_name="Async Buyer",
            customer_email="async-buyer@example.test",
            raw_text="Part P-ASYNC-1 quantity 1",
            status="Quote_Sent",
        )
        await repositories.rfq.create_from_payload(rfq.model_dump(mode="json"))
        quote = Quote(
            id=quote_id,
            rfq_id=rfq_id,
            subtotal=125.0,
            total_amount=125.0,
            lead_time_days=4,
            valid_until="2026-11-01",
            status="Sent",
        )
        await repositories.records.upsert("quotes", quote_id, quote.model_dump(mode="json"))
        item = QuoteItem(
            id="QTI-ASYNC-CUSTOMER-QUESTION",
            quote_id=quote_id,
            rfq_item_id="RFI-ASYNC-CUSTOMER-QUESTION",
            part_number="P-ASYNC-1",
            quantity=1,
            source="Inventory",
            unit_cost=100.0,
            unit_price=125.0,
            margin_percent=20.0,
            certificate_type="FAA 8130-3",
            condition="NE",
            lead_time_days=4,
        )
        await repositories.records.upsert("quote_items", item.id, item.model_dump(mode="json"))
        for index, task_key in enumerate(chase_task_keys(quote_id), start=1):
            session.add(CommunicationTaskRecord(
                id=f"TASK-ASYNC-CUSTOMER-QUESTION-{index}",
                task_key=task_key,
                recipient="async-buyer@example.test",
                subject="Follow-up",
                body="Checking in",
                task_type="customer_followup",
                mailbox="sales",
                status="pending",
                due_at=datetime.now(timezone.utc) + timedelta(days=index),
            ))

    monkeypatch.setattr(
        customer_question_service,
        "answer_from_quote",
        lambda question, approved_quote, items: "Lead time: P-ASYNC-1: 4 days",
    )
    message = {
        "message_id": "MSG-ASYNC-CUSTOMER-QUESTION-1",
        "internet_message_id": "<async-customer-question-1@example.test>",
        "from": "Async Buyer <async-buyer@example.test>",
        "subject": f"Re: Quotation {quote_id} - lead time",
        "body": "Please confirm the lead time.",
        "attachments": [],
    }
    await _process_sales_message_async(message, engine=disposable_postgres_engine)
    await _process_sales_message_async(message, engine=disposable_postgres_engine)

    async with session_scope(disposable_postgres_engine) as session:
        inbound = await session.get(InboundMessageIdempotencyRecord, message["message_id"])
        raw_email = await session.scalar(
            select(RawEmailRecord).where(
                RawEmailRecord.provider_message_id == message["message_id"]
            )
        )
        outbox_rows = list(await session.scalars(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        ))
        audit_rows = list(await session.scalars(
            select(AuditLogRecord).where(
                AuditLogRecord.rfq_id == rfq_id,
                AuditLogRecord.action_type == "customer_detail_response",
            )
        ))
        scheduled = list(await session.scalars(
            select(CommunicationTaskRecord).where(
                CommunicationTaskRecord.task_key.in_(chase_task_keys(quote_id))
            )
        ))

    assert inbound.status == "processed"
    assert raw_email is not None
    assert len(outbox_rows) == 1
    assert outbox_rows[0].recipient == "async-buyer@example.test"
    assert outbox_rows[0].reply_to == message["message_id"]
    assert "Lead time: P-ASYNC-1: 4 days" in outbox_rows[0].payload["body"]
    assert len(audit_rows) == 1
    assert all(task.status == "cancelled" for task in scheduled)


async def test_postgres_email_purchase_order_uses_async_repositories_once(
    disposable_postgres_engine, monkeypatch,
):
    from models.db_models import Quote, RFQ
    from models.async_models import PurchaseOrder
    from models.operational_models import InboundMessageIdempotencyRecord, OutboxMessageRecord
    from worker import _process_sales_message_async

    rfq_id = "RFQ-ASYNC-EMAIL-PO"
    quote_id = "QTE-4321"
    async with session_scope(disposable_postgres_engine) as session:
        repositories = create_operational_repositories(session)
        rfq = RFQ(
            id=rfq_id,
            customer_name="PO Buyer",
            customer_email="po-buyer@example.test",
            raw_text="Part P-PO-1 quantity 1",
            status="Quote_Sent",
        )
        await repositories.rfq.create_from_payload(rfq.model_dump(mode="json"))
        quote = Quote(
            id=quote_id,
            rfq_id=rfq_id,
            subtotal=125.0,
            total_amount=125.0,
            status="Sent",
        )
        await repositories.records.upsert("quotes", quote_id, quote.model_dump(mode="json"))
        await repositories.records.upsert("quote_items", "QTI-ASYNC-EMAIL-PO", {
            "id": "QTI-ASYNC-EMAIL-PO",
            "quote_id": quote_id,
            "rfq_item_id": "RFI-ASYNC-EMAIL-PO",
            "part_number": "P-PO-1",
            "quantity": 1,
            "source": "Inventory",
            "unit_price": 125.0,
            "unit_cost": 100.0,
            "margin_percent": 20.0,
            "certificate_type": "FAA 8130-3",
        })

    message = {
        "message_id": "MSG-ASYNC-EMAIL-PO",
        "internet_message_id": "<async-email-po@example.test>",
        "from": "PO Buyer <po-buyer@example.test>",
        "subject": "Purchase Order Number: PO-4321",
        "body": "Please find our purchase order attached.",
        "attachments": [{
            "filename": "PO-4321.pdf",
            "content_type": "application/pdf",
            "content": b"pdf",
        }],
    }
    monkeypatch.setenv("CAMILA_NOTIFICATION_EMAIL", "review@example.test")
    monkeypatch.setattr(
        "worker._ingest_sales_message",
        AsyncMock(side_effect=AssertionError("synchronous mailbox fallback used")),
    )

    assert await _process_sales_message_async(message, engine=disposable_postgres_engine)
    assert await _process_sales_message_async(message, engine=disposable_postgres_engine)

    async with session_scope(disposable_postgres_engine) as session:
        inbound = await session.get(InboundMessageIdempotencyRecord, message["message_id"])
        purchase_orders = list(await session.scalars(
            select(PurchaseOrder).where(PurchaseOrder.received_message_id == message["internet_message_id"])
        ))
        outbox_rows = list(await session.scalars(
            select(OutboxMessageRecord).where(OutboxMessageRecord.entity_id == quote_id)
        ))
        repositories = create_operational_repositories(session)
        rfq_payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)

    assert inbound.status == "processed"
    assert rfq_payload["status"] == "Pending_PO_Review"
    assert len(purchase_orders) == 1
    assert purchase_orders[0].po_number == "PO-4321"
    assert purchase_orders[0].status == "Pending_PO_Review"
    assert purchase_orders[0].attachment_metadata == [{
        "filename": "PO-4321.pdf",
        "content_type": "application/pdf",
        "size": 3,
    }]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].recipient == "review@example.test"
    assert outbox_rows[0].status == "PENDING"


async def test_postgres_multi_process_inbound_claim_is_idempotent(disposable_postgres_engine):
    async with disposable_postgres_engine.connect() as connection:
        schema_name = await connection.scalar(text("SELECT current_schema()"))
    sync_url = disposable_postgres_engine.url.set(
        drivername="postgresql+psycopg2"
    ).update_query_dict({"options": f"-csearch_path={schema_name}"})

    message_id = "PG18-MULTIPROCESS-IDEMPOTENCY-1"
    with ProcessPoolExecutor(
        max_workers=6, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        claims = list(executor.map(
            _claim_inbound_message_in_process,
            [sync_url.render_as_string(hide_password=False)] * 6,
            [message_id] * 6,
        ))

    assert sum(claims) == 1


async def test_postgres_concurrent_reservation_idempotency_and_outbox_claims(disposable_postgres_engine):
    async with session_scope(disposable_postgres_engine) as session:
        session.add(OperationalRecord(
            domain="inventory",
            record_id="PG18-CONCURRENT-INVENTORY-1",
            payload={"part_number": "PG18-CONCURRENT-PART", "quantity_available": 1},
        ))

    async with disposable_postgres_engine.connect() as connection:
        schema_name = await connection.scalar(text("SELECT current_schema()"))
    sync_url = disposable_postgres_engine.url.set(
        drivername="postgresql+psycopg2"
    ).update_query_dict({"options": f"-csearch_path={schema_name}"})
    sync_engine = create_engine(sync_url, pool_size=8, max_overflow=0)
    try:
        repository = PostgresReviewTelemetryRepository(engine=sync_engine)
        with ThreadPoolExecutor(max_workers=8) as executor:
            reservations = list(executor.map(
                lambda _index: repository.reserve_inventory("PG18-CONCURRENT-PART", 1),
                range(8),
            ))
        assert sum(reservations) == 1

        claims = list(
            repository.claim_inbound_message("PG18-IDEMPOTENT-MESSAGE", "purchasing")
            for _ in range(8)
        )
        assert sum(claims) == 1

        for index in range(4):
            repository.enqueue_outbox_message(
                deduplication_key=f"pg18-reliability-{index}",
                mailbox="sales",
                recipient="buyer@example.test",
                subject=f"PG18 reliability {index}",
                body="Disposable test message",
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed_batches = list(executor.map(
                lambda _index: repository.claim_outbox_messages(limit=2), range(2)
            ))
        claimed_ids = [row["id"] for batch in claimed_batches for row in batch]
        assert len(claimed_ids) == 4
        assert len(set(claimed_ids)) == 4
        assert repository.fail_outbox_message(
            claimed_ids[0], "Unknown external delivery outcome", retryable=False
        ) == "MANUAL_REVIEW_REQUIRED"
    finally:
        sync_engine.dispose()