from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from api.main import app


def test_production_readiness_requires_postgres_mirroring(monkeypatch):
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]


def test_readiness_does_not_expose_database_exception_details(monkeypatch):
    monkeypatch.setenv("WT_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "api.main.db_service.list_rfqs",
        Mock(side_effect=RuntimeError("SELECT * FROM users; password=do-not-leak")),
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database readiness check failed."
    assert "SELECT" not in response.text
    assert "password" not in response.text


async def test_production_readiness_uses_async_repositories_without_sync_db_service(monkeypatch):
    from api import main

    class Session:
        pass

    class RFQRepository:
        async def list_operational_records(self, domain):
            assert domain == "rfqs"
            return {}

        async def list(self):
            return []

    class Repositories:
        rfq = RFQRepository()

        async def check_readiness(self):
            return {"inventory": True, "rfq": True, "supplier": True, "quote": True}

    class Engine:
        async def dispose(self):
            return None

    @asynccontextmanager
    async def fake_session_scope(_engine):
        yield Session()

    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db.example/production")
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "true")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "true")
    monkeypatch.setattr(main, "create_engine_from_environment", Engine)
    monkeypatch.setattr(main, "preflight_database", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "check_migration_state", AsyncMock(return_value={"ready": True}))
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=Repositories()))
    monkeypatch.setattr(main, "persistence_status", Mock(return_value={
        "inventory_postgres_mirror_enabled": True,
        "full_operational_persistence_ready": True,
    }))
    monkeypatch.setattr(main.db_service, "list_rfqs", Mock(side_effect=AssertionError("sync db_service used")))

    result = await main.ready()

    assert result["status"] == "ready"


async def test_rfq_list_route_uses_async_db_service_when_session_is_available(monkeypatch):
    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-ASYNC-LIST",
        customer_name="Async Buyer",
        customer_email="buyer@example.test",
        raw_text="Need part 123",
    )
    async_list = AsyncMock(return_value=[rfq])
    monkeypatch.setattr(main.db_service, "list_rfqs_async", async_list)

    result = await main.list_rfqs(
        user={"role": "ROLE_ADMIN", "email": "admin@example.test"},
        session=object(),
    )

    assert [item.id for item in result] == [rfq.id]
    async_list.assert_awaited_once()


async def test_operational_record_repository_filters_by_domain_and_payload_value():
    from types import SimpleNamespace

    from repositories.runtime import OperationalRecordRepository

    record = SimpleNamespace(
        record_id="ITEM-1",
        payload={"rfq_id": "RFQ-1", "part_number": "PN-1"},
    )

    class Session:
        statement = None

        async def scalars(self, statement):
            self.statement = statement
            return [record]

    session = Session()
    result = await OperationalRecordRepository(session).list_by_payload_value(
        "rfq_items", "rfq_id", "RFQ-1"
    )

    assert result == {"ITEM-1": record.payload}
    compiled = session.statement.compile().params
    assert "rfq_items" in compiled.values()
    assert "rfq_id" in compiled.values()
    assert "RFQ-1" in compiled.values()


async def test_rfq_detail_uses_parent_scoped_operational_record_queries(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, call

    from api import main

    rfq = {
        "id": "RFQ-DETAIL-1", "customer_name": "Buyer",
        "customer_email": "buyer@example.test", "raw_text": "Need PN-1",
    }
    rfq_item = {
        "id": "ITEM-1", "rfq_id": "RFQ-DETAIL-1",
        "requested_part_number": "PN-1", "quantity": 1,
    }
    quote = {
        "id": "QUOTE-1", "rfq_id": "RFQ-DETAIL-1",
        "subtotal": 100, "shipping_cost": 0, "total_amount": 100,
    }
    quote_item = {
        "id": "QUOTE-ITEM-1", "quote_id": "QUOTE-1", "rfq_item_id": "ITEM-1",
        "part_number": "PN-1", "quantity": 1, "unit_price": 100,
        "source": "Inventory", "unit_cost": 50, "margin_percent": 50,
        "certificate_type": "FAA 8130-3",
    }
    records = SimpleNamespace(list_by_payload_value=AsyncMock(side_effect=[
        {"ITEM-1": rfq_item},
        {"QUOTE-1": quote},
        {"QUOTE-ITEM-1": quote_item},
    ]))
    rfq_repository = SimpleNamespace(
        get_operational_record=AsyncMock(return_value=rfq),
    )
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(rfq=rfq_repository, records=records)),
    )

    result = await main.get_rfq_detail(
        "RFQ-DETAIL-1",
        user={"role": "ROLE_CUSTOMER", "email": "buyer@example.test"},
        session=object(),
    )

    assert [item.id for item in result.items] == ["ITEM-1"]
    assert result.quote_details.quote.id == "QUOTE-1"
    assert [item.part_number for item in result.quote_details.items] == ["PN-1"]
    assert records.list_by_payload_value.await_args_list == [
        call("rfq_items", "rfq_id", "RFQ-DETAIL-1"),
        call("quotes", "rfq_id", "RFQ-DETAIL-1"),
        call("quote_items", "quote_id", "QUOTE-1"),
    ]


async def test_async_shipment_reads_filter_events_and_sort_shipments():
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from models.db_models import Shipment, ShipmentEvent
    from services.db_service import db_service

    now = datetime.now(timezone.utc)
    older = Shipment(
        id="SHP-OLD", rfq_id="RFQ-1", customer_email="old@example.test",
        public_token="old-token", updated_at=now - timedelta(days=1),
    )
    newer = Shipment(
        id="SHP-NEW", rfq_id="RFQ-2", customer_email="new@example.test",
        public_token="new-token", updated_at=now,
    )
    events = {
        "e2": ShipmentEvent(id="e2", shipment_id="SHP-NEW", status="Delivered", description="Delivered", occurred_at=now).model_dump(mode="json"),
        "e1": ShipmentEvent(id="e1", shipment_id="SHP-NEW", status="In Transit", description="Moved", occurred_at=now - timedelta(hours=1)).model_dump(mode="json"),
        "other": ShipmentEvent(id="other", shipment_id="SHP-OLD", status="Created", description="Created").model_dump(mode="json"),
    }
    records = SimpleNamespace(list=AsyncMock(side_effect=[
        {older.id: older.model_dump(mode="json"), newer.id: newer.model_dump(mode="json")},
        {older.id: older.model_dump(mode="json"), newer.id: newer.model_dump(mode="json")},
        events,
    ]))
    repositories = SimpleNamespace(records=records)

    assert (await db_service.get_shipment_by_token_async(repositories, "new-token")).id == newer.id
    assert [shipment.id for shipment in await db_service.list_shipments_async(repositories)] == [newer.id, older.id]
    assert [event.id for event in await db_service.get_shipment_events_async(repositories, newer.id)] == ["e1", "e2"]


async def test_async_supplier_directory_route_uses_repository(monkeypatch):
    from types import SimpleNamespace

    from api import main

    records = [{
        "id": "SUP-1", "company_name": "Supplier", "phone": "555-0100", "email": "quotes@example.test",
        "approval_status": "Approved", "itar_certified": True,
    }]
    list_suppliers = AsyncMock(return_value=records)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(list_suppliers=list_suppliers))),
    )

    result = await main.list_suppliers(_user={}, session=object())

    assert result[0].id == "SUP-1"
    assert result[0].approval_status == "Approved"
    list_suppliers.assert_awaited_once()


async def test_async_supplier_offers_route_uses_repository(monkeypatch):
    from types import SimpleNamespace

    from api import main

    offers = [{"supplier_part_id": "OFFER-1", "part_number": "PN-1", "supplier_name": "Supplier"}]
    offers_for_part = AsyncMock(return_value=offers)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(offers_for_part=offers_for_part))),
    )

    result = await main.list_supplier_offers(part_number=" pn-1 ", _user={}, session=object())

    assert result == offers
    offers_for_part.assert_awaited_once_with("PN-1", quantity_needed=1)


async def test_async_supplier_detail_route_uses_operational_profile(monkeypatch):
    from types import SimpleNamespace

    from api import main

    profile = {
        "id": "SUP-1", "company_name": "Supplier", "contact_name": "Contact",
        "phone": "555-0100", "email": "quotes@example.test", "address_line1": "1 Main",
        "city": "Town", "state_province": "CA", "postal_code": "90000", "country": "US",
        "approval_status": "Approved", "itar_certified": True,
    }
    get_profile = AsyncMock(return_value=profile)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(get_profile=get_profile))),
    )

    result = await main.get_supplier(supplier_id="SUP-1", _user={}, session=object())

    assert result.id == "SUP-1"
    assert result.address_line1 == "1 Main"
    get_profile.assert_awaited_once_with("SUP-1")


async def test_inventory_route_uses_async_operational_records(monkeypatch):
    from types import SimpleNamespace

    from api import main

    inventory = {
        "INV-1": {
            "id": "INV-1", "part_number": "PN-1", "serial_number": "SN-1",
            "quantity_available": 3, "condition_code": "NE", "warehouse_location": "A1",
            "unit_cost": 10.0, "certificate_type": "CoC", "has_full_trace": True,
        }
    }
    list_records = AsyncMock(return_value=inventory)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(records=SimpleNamespace(list=list_records))),
    )
    monkeypatch.setattr(
        main.db_service,
        "inventory",
        SimpleNamespace(values=Mock(side_effect=AssertionError("sync inventory map used"))),
    )

    result = await main.get_inventory(_user={}, session=object())

    assert [item.id for item in result] == ["INV-1"]
    list_records.assert_awaited_once_with("inventory")


async def test_catalog_search_uses_async_inventory_and_safe_supplier_offer_projection(monkeypatch):
    from types import SimpleNamespace

    from api import main

    inventory = {
        "INV-1": {
            "id": "INV-1", "part_number": "PN-1", "serial_number": "SN-1",
            "quantity_available": 3, "condition_code": "NE", "warehouse_location": "A1",
            "unit_cost": 10.0, "certificate_type": "CoC", "has_full_trace": True,
        }
    }
    list_records = AsyncMock(return_value=inventory)
    search_offers = AsyncMock(return_value=[{
        "supplier_part_id": "OFFER-1", "part_number": "PN-2", "quantity_available": 2,
        "condition_code": "FN", "certificate_type": "FAA 8130-3", "unit_cost": 99.0,
        "supplier_email": "supplier@example.test",
    }])
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(
            records=SimpleNamespace(list=list_records),
            supplier=SimpleNamespace(search_offers=search_offers),
        )),
    )
    monkeypatch.setenv("INVENTORY_INGESTION_POSTGRES_ENABLED", "false")

    result = await main.search_catalog(
        query="pn-", condition=None, _user={}, session=object()
    )

    assert [(item.part_number, item.condition_code) for item in result] == [("PN-1", "NE"), ("PN-2", "FN")]
    assert all(not hasattr(item, "unit_cost") for item in result)
    list_records.assert_awaited_once_with("inventory")
    search_offers.assert_awaited_once_with("pn-", None)