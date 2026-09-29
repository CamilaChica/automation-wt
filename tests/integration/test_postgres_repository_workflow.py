from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from api.auth import current_user
from api.main import app
from models.db_models import RFQ
from models.operational_models import OperationalRecord, SupplierInventoryRowRecord
from repositories.review_telemetry_repository import PostgresReviewTelemetryRepository
from services.async_database import get_async_db, session_scope
from repositories.runtime import create_operational_repositories
from services.supplier_database import PostgresSupplierDatabase


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
    assert record is not None
    assert payload is not None
    assert payload["customer_email"] == "async-intake@example.test"