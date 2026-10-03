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


def test_liveness_stays_healthy_while_postgres_readiness_is_blocked(monkeypatch):
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert "DATABASE_URL" in ready.json()["detail"]


async def test_production_startup_skips_postgres_ping_while_runtime_is_disabled(monkeypatch):
    from api import main

    preflight = AsyncMock(side_effect=AssertionError("startup must not ping postgres while runtime is off"))
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false")
    monkeypatch.setattr(main, "preflight_database", preflight)
    monkeypatch.setattr(main, "initialize_voice_media", Mock())

    await main.initialize_local_voice_recordings()

    preflight.assert_not_awaited()


async def test_production_startup_checks_postgres_when_runtime_is_enabled(monkeypatch):
    from api import main

    preflight = AsyncMock(return_value=None)
    monkeypatch.setenv("WT_ENV", "production")
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "true")
    monkeypatch.setattr(main, "preflight_database", preflight)
    monkeypatch.setattr(main, "initialize_voice_media", Mock())

    await main.initialize_local_voice_recordings()

    preflight.assert_awaited_once_with()


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
    monkeypatch.setenv("OPERATIONAL_POSTGRES_RUNTIME_ENABLED", "false")
    monkeypatch.setattr(main, "create_engine_from_environment", Engine)
    monkeypatch.setattr(main, "preflight_database", AsyncMock(return_value=None))
    monkeypatch.setattr(main, "check_migration_state", AsyncMock(return_value={"ready": True}))
    monkeypatch.setattr(main, "session_scope", fake_session_scope)
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=Repositories()))
    monkeypatch.setattr(main, "persistence_status", Mock(return_value={
        "inventory_postgres_mirror_enabled": True,
        "operational_postgres_cutover_ready": True,
        "full_operational_persistence_ready": False,
    }))
    monkeypatch.setattr(main.db_service, "list_rfqs", Mock(side_effect=AssertionError("sync db_service used")))

    result = await main.ready()

    assert result["status"] == "ready"
    assert result["operational_postgres_cutover_ready"] is True
    assert result["full_operational_persistence_ready"] is False


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


async def test_customer_rfq_detail_uses_parent_scoped_record_queries(monkeypatch):
    from types import SimpleNamespace

    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-DETAIL-ASYNC", customer_name="Buyer", customer_email="buyer@example.test",
        raw_text="Need PN-ASYNC-1",
    )
    rfq_payload = rfq.model_dump(mode="json")
    rfq_item = {
        "id": "ITEM-ASYNC-1", "rfq_id": rfq.id, "requested_part_number": "PN-ASYNC-1",
        "quantity": 1, "uom": "EA",
    }
    quote = {
        "id": "QUOTE-ASYNC-1", "rfq_id": rfq.id, "subtotal": 100,
        "shipping_cost": 0, "total_amount": 100, "status": "Sent",
    }
    quote_item = {
        "id": "QUOTE-ITEM-ASYNC-1", "quote_id": quote["id"], "rfq_item_id": rfq_item["id"],
        "part_number": "PN-ASYNC-1", "description": "Part", "quantity": 1, "uom": "EA",
        "source": "Inventory", "unit_cost": 50, "unit_price": 100, "margin_percent": 50,
        "certificate_type": "FAA 8130-3", "compliance_status": "Pass",
    }
    scoped_records = AsyncMock(side_effect=[
        {rfq_item["id"]: rfq_item},
        {quote["id"]: quote, "QUOTE-OTHER": {**quote, "id": "QUOTE-OTHER", "rfq_id": "RFQ-OTHER"}},
        {quote_item["id"]: quote_item},
    ])
    rfq_repository = SimpleNamespace(get_operational_record=AsyncMock(return_value=rfq_payload))
    repositories = SimpleNamespace(
        rfq=rfq_repository,
        quote=SimpleNamespace(),
        records=SimpleNamespace(list_by_payload_value=scoped_records),
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(
        main.communication_service, "cancel_customer_followups_async", AsyncMock(return_value=None)
    )

    result = await main.get_rfq_detail(
        rfq.id,
        user={"role": "ROLE_CUSTOMER", "email": "buyer@example.test"},
        session=object(),
    )

    assert [item.id for item in result.items] == [rfq_item["id"]]
    assert result.quote_details.quote.id == quote["id"]
    assert [item.part_number for item in result.quote_details.items] == ["PN-ASYNC-1"]
    assert [awaited.args for awaited in scoped_records.await_args_list] == [
        ("rfq_items", "rfq_id", rfq.id),
        ("quotes", "rfq_id", rfq.id),
        ("quote_items", "quote_id", quote["id"]),
    ]


async def test_failed_intake_reset_uses_atomic_async_repository_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from api import main

    reset_failed_intake = AsyncMock(return_value=True)
    rfq_repository = SimpleNamespace(
        get_operational_record=AsyncMock(return_value={"id": "RFQ-RESET-ASYNC", "status": "Intake_Failed"}),
        get=AsyncMock(return_value=None),
        reset_failed_intake=reset_failed_intake,
    )
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(rfq=rfq_repository)),
    )
    monkeypatch.setattr(main.db_service, "get_rfq", Mock(side_effect=AssertionError("sync RFQ read used")))
    monkeypatch.setattr(main.db_service, "update_rfq_status", Mock(side_effect=AssertionError("sync RFQ update used")))

    result = await main.reset_failed_intake(
        "RFQ-RESET-ASYNC",
        main.FailedIntakeResetRequest(reason=" Verified correction "),
        user={"email": "operator@example.test", "role": "ROLE_ADMIN"},
        session=object(),
    )

    assert result == {
        "rfq_id": "RFQ-RESET-ASYNC", "status": "Intake",
        "reset_by": "operator@example.test", "reason": "Verified correction",
    }
    reset_failed_intake.assert_awaited_once_with(
        "RFQ-RESET-ASYNC",
        "Failed intake reset to Intake by operator@example.test. Reason: Verified correction",
    )


async def test_automation_pause_route_uses_atomic_async_repository_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from api import main

    pause = AsyncMock(return_value={
        "rfq_id": "RFQ-PAUSE-ASYNC", "automation_paused": True,
        "pause_reason": "Waiting for export-control review.",
    })
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(rfq=SimpleNamespace(set_automation_paused=pause))),
    )
    monkeypatch.setattr(
        main.orchestration_service,
        "set_automation_pause",
        Mock(side_effect=AssertionError("synchronous orchestration mutation used")),
    )

    result = await main.set_automation_pause(
        "RFQ-PAUSE-ASYNC",
        main.AutomationPauseRequest(paused=True, reason="Waiting for export-control review."),
        user={"email": "operator@example.test", "role": "ROLE_ADMIN"},
        session=object(),
    )

    assert result["automation_paused"] is True
    pause.assert_awaited_once_with(
        "RFQ-PAUSE-ASYNC", True, "Waiting for export-control review.", "operator@example.test"
    )


async def test_trace_decision_route_uses_async_repository_when_available(monkeypatch):
    from types import SimpleNamespace

    from api import main

    decision = AsyncMock(return_value={
        "rfq_id": "RFQ-TRACE-ASYNC", "decision": "freeze", "automation_paused": True,
    })
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(rfq=SimpleNamespace(record_trace_decision=decision))),
    )
    monkeypatch.setattr(
        main.orchestration_service,
        "record_trace_decision",
        Mock(side_effect=AssertionError("synchronous orchestration mutation used")),
    )

    result = await main.record_trace_decision(
        "RFQ-TRACE-ASYNC",
        main.TraceDecisionRequest(decision="freeze", reason="Trace discrepancy requires review."),
        user={"email": "operator@example.test", "role": "ROLE_ADMIN"},
        session=object(),
    )

    assert result["automation_paused"] is True
    decision.assert_awaited_once_with(
        "RFQ-TRACE-ASYNC", "freeze", "Trace discrepancy requires review."
    )


async def test_internal_rfq_detail_reads_audit_logs_asynchronously(monkeypatch):
    from types import SimpleNamespace

    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-AUDIT-ASYNC", customer_name="Buyer", customer_email="buyer@example.test",
        raw_text="Need PN-1",
    )
    repositories = SimpleNamespace(
        rfq=SimpleNamespace(
            get_operational_record=AsyncMock(return_value=rfq.model_dump(mode="json")),
            get=AsyncMock(return_value=None),
            audit_logs=AsyncMock(return_value=[]),
        ),
        quote=SimpleNamespace(list_operational_records=AsyncMock(return_value={})),
        records=SimpleNamespace(list_by_payload_value=AsyncMock(side_effect=[{}, {}])),
    )
    logs = [{"id": 1, "rfq_id": rfq.id, "agent_name": "Test", "action_type": "read", "message": "audit"}]
    async_logs = AsyncMock(return_value=logs)
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "get_audit_logs_async", async_logs)
    monkeypatch.setattr(main.db_service, "get_audit_logs", Mock(side_effect=AssertionError("sync audit read used")))

    result = await main.get_rfq_detail(
        rfq.id, user={"role": "ROLE_ADMIN", "email": "admin@example.test"}, session=object()
    )

    assert result["logs"] == logs
    async_logs.assert_awaited_once_with(repositories, rfq.id)


async def test_customer_shipment_tracking_route_uses_async_repository_when_available(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from api import main
    from models.db_models import Shipment, ShipmentEvent

    shipment = Shipment(
        id="SHP-ASYNC-1", rfq_id="RFQ-ASYNC-1", customer_email="buyer@example.test",
        public_token="opaque-token", part_numbers=["PN-1"], quantity=1,
    )
    event = ShipmentEvent(
        id="EVT-ASYNC-1", shipment_id=shipment.id, status="In Transit",
        description="Departed", occurred_at=datetime.now(timezone.utc),
    )
    get_by_token = AsyncMock(return_value=shipment)
    get_events = AsyncMock(return_value=[event])
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(main.db_service, "get_shipment_by_token_async", get_by_token)
    monkeypatch.setattr(main.db_service, "get_shipment_events_async", get_events)
    monkeypatch.setattr(
        main.db_service, "get_shipment_by_token",
        Mock(side_effect=AssertionError("sync shipment read used")),
    )

    result = await main.track_shipment("opaque-token", session=object())

    assert result["shipment_id"] == shipment.id
    assert result["events"][0]["id"] == event.id
    get_by_token.assert_awaited_once()
    get_events.assert_awaited_once()
    assert get_events.await_args.args[1] == shipment.id


async def test_internal_shipment_list_route_uses_async_repository_when_available(monkeypatch):
    from types import SimpleNamespace

    from api import main
    from models.db_models import Shipment

    shipment = Shipment(
        id="SHP-ASYNC-LIST", rfq_id="RFQ-ASYNC-1", customer_email="buyer@example.test",
        public_token="token-1", part_numbers=["PN-1"], quantity=1,
    )
    list_async = AsyncMock(return_value=[shipment])
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(main.db_service, "list_shipments_async", list_async)
    monkeypatch.setattr(
        main.db_service, "list_shipments",
        Mock(side_effect=AssertionError("sync shipment list used")),
    )

    result = await main.list_shipments(_user={"role": "ROLE_ADMIN"}, session=object())

    assert [item.id for item in result] == [shipment.id]
    list_async.assert_awaited_once()


async def test_shipment_event_route_uses_async_repository_when_available(monkeypatch):
    from types import SimpleNamespace

    from api import main
    from models.db_models import ShipmentEvent

    event = ShipmentEvent(
        id="SHE-ASYNC-1", shipment_id="SHP-ASYNC-1", status="Packed",
        location="MIA warehouse", description="Passed final inspection.",
    )
    add_event = AsyncMock(return_value=event)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace()),
    )
    monkeypatch.setattr(main.db_service, "add_shipment_event_async", add_event)
    monkeypatch.setattr(
        main.db_service, "get_shipment",
        Mock(side_effect=AssertionError("sync shipment read used")),
    )
    monkeypatch.setattr(
        main.db_service, "add_shipment_event",
        Mock(side_effect=AssertionError("sync shipment event write used")),
    )

    result = await main.add_shipment_event(
        "SHP-ASYNC-1",
        main.ShipmentEventRequest(
            status="Packed", location="MIA warehouse", description="Passed final inspection."
        ),
        _user={"role": "ROLE_PURCHASING"},
        session=object(),
    )

    assert result["event"].id == event.id
    add_event.assert_awaited_once()


async def test_async_shipment_event_updates_shipment_and_event_records():
    from types import SimpleNamespace

    from models.db_models import Shipment
    from services.db_service import db_service

    shipment = Shipment(
        id="SHP-ASYNC-WRITE", rfq_id="RFQ-ASYNC-WRITE", customer_email="buyer@example.test",
        public_token="token-async-write", part_numbers=["PN-1"], quantity=1,
    )
    upsert = AsyncMock()
    records = SimpleNamespace(get=AsyncMock(return_value=shipment.model_dump(mode="json")), upsert=upsert)

    event = await db_service.add_shipment_event_async(
        SimpleNamespace(records=records),
        shipment.id,
        "Packed",
        "MIA warehouse",
        "Passed final inspection.",
    )

    assert event is not None
    assert event.shipment_id == shipment.id
    assert upsert.await_count == 2
    shipment_write, event_write = upsert.await_args_list
    assert shipment_write.args[0:2] == ("shipments", shipment.id)
    assert shipment_write.args[2]["status"] == "Packed"
    assert event_write.args[0:2] == ("shipment_events", event.id)
    assert event_write.args[2]["description"] == "Passed final inspection."


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
    records = SimpleNamespace(
        list=AsyncMock(return_value={
            older.id: older.model_dump(mode="json"),
            newer.id: newer.model_dump(mode="json"),
        }),
        list_by_payload_value=AsyncMock(side_effect=[
            {newer.id: newer.model_dump(mode="json")},
            {event_id: payload for event_id, payload in events.items() if payload["shipment_id"] == newer.id},
        ]),
    )
    repositories = SimpleNamespace(records=records)

    assert (await db_service.get_shipment_by_token_async(repositories, "new-token")).id == newer.id
    assert [shipment.id for shipment in await db_service.list_shipments_async(repositories)] == [newer.id, older.id]
    assert [event.id for event in await db_service.get_shipment_events_async(repositories, newer.id)] == ["e1", "e2"]
    assert records.list_by_payload_value.await_args_list[0].args == (
        "shipments", "public_token", "new-token"
    )
    assert records.list_by_payload_value.await_args_list[1].args == (
        "shipment_events", "shipment_id", newer.id
    )


async def test_inventory_route_reads_through_async_operational_records(monkeypatch):
    from types import SimpleNamespace

    from api import main

    inventory = {
        "id": "INV-1", "part_number": "PN-1", "serial_number": "SN-1",
        "quantity_available": 2, "condition_code": "NE", "warehouse_location": "MIA-A1",
        "unit_cost": 50, "certificate_type": "FAA 8130-3", "has_full_trace": True,
    }
    list_records = AsyncMock(return_value={"INV-1": inventory})
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(records=SimpleNamespace(list=list_records))),
    )

    result = await main.get_inventory(_user={"role": "ROLE_ADMIN"}, session=object())

    assert [item.id for item in result] == ["INV-1"]
    list_records.assert_awaited_once_with("inventory")


async def test_supplier_directory_route_reads_async_and_returns_valid_profiles(monkeypatch):
    from types import SimpleNamespace

    from api import main

    rows = [{
        "id": "SUP-ASYNC-1", "company_name": "Supplier Co", "email": "sales@example.test",
        "phone": "555-0100", "approval_status": "Approved", "itar_certified": True,
    }]
    list_suppliers = AsyncMock(return_value=rows)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(list_suppliers=list_suppliers))),
    )

    result = await main.list_suppliers(_user={"role": "ROLE_ADMIN"}, session=object())

    assert result[0].id == "SUP-ASYNC-1"
    assert result[0].contact_name == "Supplier Co"
    assert result[0].address_line1 == ""
    list_suppliers.assert_awaited_once()


async def test_supplier_offer_route_uses_async_repository_and_ui_id_alias(monkeypatch):
    from types import SimpleNamespace

    from api import main

    offers = [{
        "supplier_part_id": "SUP-PART-1", "supplier_id": "SUP-1", "part_number": "PN-1",
        "quantity_available": 4, "unit_cost": 12.5, "condition_code": "NE",
        "certificate_type": "CoC", "lead_time_days": 3, "supplier_name": "Supplier",
    }]
    offers_for_part = AsyncMock(return_value=offers)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(offers_for_part=offers_for_part))),
    )

    result = await main.list_supplier_offers(
        part_number=" pn-1 ", _user={"role": "ROLE_PURCHASING"}, session=object()
    )

    assert result[0]["id"] == "SUP-PART-1"
    assert result[0]["condition"] == "NE"
    offers_for_part.assert_awaited_once_with("PN-1", quantity_needed=1)


async def test_supplier_profile_route_reads_async_operational_profile(monkeypatch):
    from types import SimpleNamespace

    from api import main

    profile = {
        "id": "SUP-ASYNC-2", "company_name": "Profile Supplier", "contact_name": "Contact",
        "phone": "555-0100", "email": "contact@example.test", "address_line1": "1 Main",
        "city": "Town", "state_province": "CA", "postal_code": "90000", "country": "US",
        "approval_status": "Approved", "itar_certified": False,
    }
    get_profile = AsyncMock(return_value=profile)
    monkeypatch.setattr(
        main, "create_operational_repositories",
        Mock(return_value=SimpleNamespace(supplier=SimpleNamespace(get_profile=get_profile))),
    )

    result = await main.get_supplier(
        "SUP-ASYNC-2", _user={"role": "ROLE_PURCHASING"}, session=object()
    )

    assert result.id == "SUP-ASYNC-2"
    assert result.address_line1 == "1 Main"
    get_profile.assert_awaited_once_with("SUP-ASYNC-2")


async def test_voice_dashboard_uses_async_rfq_repository_when_available(monkeypatch):
    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-VOICE-ASYNC", customer_name="Voice Buyer", customer_email="buyer@example.test",
        raw_text="Need PN-1",
    )
    list_rfqs = AsyncMock(return_value=[rfq])
    monkeypatch.setattr(main.db_service, "list_rfqs_async", list_rfqs)
    monkeypatch.setattr(
        main.db_service, "list_rfqs", Mock(side_effect=AssertionError("sync RFQ list used"))
    )
    from types import SimpleNamespace

    repositories = SimpleNamespace(records=SimpleNamespace(list=AsyncMock(return_value={})))
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main, "get_voice_dashboard", Mock(return_value={"rfq_count": 1}))

    result = await main.voice_dashboard(_user={"role": "ROLE_ADMIN"}, session=object())

    assert result == {"rfq_count": 1}
    list_rfqs.assert_awaited_once()


async def test_voice_order_status_tool_uses_async_rfq_repository_when_available(monkeypatch):
    from api import main
    from models.db_models import RFQ

    rfq = RFQ(
        id="RFQ-VOICE-TOOL-ASYNC", customer_name="Voice Buyer", customer_email="buyer@example.test",
        raw_text="Need PN-1",
    )
    list_rfqs = AsyncMock(return_value=[rfq])
    get_status = Mock(return_value={"found": True, "id": rfq.id})
    monkeypatch.setattr(main.db_service, "list_rfqs_async", list_rfqs)
    monkeypatch.setattr(
        main.db_service, "list_rfqs", Mock(side_effect=AssertionError("sync RFQ list used"))
    )
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=object()))
    monkeypatch.setattr(main, "get_customer_order_status", get_status)

    result = await main.execute_voice_tool(
        "get_order_status",
        main.VoiceToolRequest(rfq_or_order_id=rfq.id),
        user={"role": "ROLE_CUSTOMER", "email": "buyer@example.test"},
        session=object(),
    )

    assert result == {"found": True, "id": rfq.id}
    list_rfqs.assert_awaited_once()
    get_status.assert_called_once_with(rfq.id, "buyer@example.test", [rfq])


async def test_carrier_tracking_routes_use_async_shipment_repository(monkeypatch):
    from types import SimpleNamespace

    from api import main

    shipment = SimpleNamespace(
        id="SHP-TRACK-ASYNC", carrier="FedEx", tracking_number="FDX-1"
    )
    update_tracking = AsyncMock(return_value=shipment)
    get_shipment = AsyncMock(return_value=shipment)
    add_event = AsyncMock(return_value={"id": "EVT-TRACK-ASYNC", "status": "In Transit"})
    repositories = SimpleNamespace()
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "update_shipment_tracking_async", update_tracking)
    monkeypatch.setattr(main.db_service, "get_shipment_async", get_shipment)
    monkeypatch.setattr(main.db_service, "add_shipment_event_async", add_event)
    monkeypatch.setattr(main.db_service, "update_shipment_tracking", Mock(side_effect=AssertionError("sync shipment update used")))
    monkeypatch.setattr(main.db_service, "get_shipment", Mock(side_effect=AssertionError("sync shipment read used")))
    monkeypatch.setattr(main.db_service, "add_shipment_event", Mock(side_effect=AssertionError("sync shipment event write used")))
    monkeypatch.setattr(main.carrier_tracking_service, "create_tracker", Mock(return_value={"tracker_id": "TRACK-1"}))
    monkeypatch.setattr(main.carrier_tracking_service, "get_tracker", Mock(return_value={"raw": True}))
    monkeypatch.setattr(main.carrier_tracking_service, "normalize_webhook", Mock(return_value={
        "status": "In Transit", "location": "MIA", "description": "Departed",
    }))

    registration = await main.register_carrier_tracking(
        shipment.id,
        main.CarrierTrackingRequest(carrier="FedEx", tracking_number="FDX-1"),
        _user={"role": "ROLE_PURCHASING"},
        session=object(),
    )
    refreshed = await main.refresh_carrier_tracking(
        shipment.id, _user={"role": "ROLE_PURCHASING"}, session=object()
    )

    assert registration["provider"] == {"tracker_id": "TRACK-1"}
    assert refreshed["event"]["id"] == "EVT-TRACK-ASYNC"
    update_tracking.assert_awaited_once_with(repositories, shipment.id, "FedEx", "FDX-1")
    get_shipment.assert_awaited_once_with(repositories, shipment.id)
    add_event.assert_awaited_once_with(repositories, shipment.id, "In Transit", "MIA", "Departed")


async def test_shipment_sms_route_uses_async_shipment_lookup(monkeypatch):
    from types import SimpleNamespace

    from api import main

    shipment = SimpleNamespace(id="SHP-SMS-ASYNC")
    get_shipment = AsyncMock(return_value=shipment)
    send_update = Mock(return_value={"status": "DRY_RUN"})
    repositories = SimpleNamespace()
    monkeypatch.setattr(main, "create_operational_repositories", Mock(return_value=repositories))
    monkeypatch.setattr(main.db_service, "get_shipment_async", get_shipment)
    monkeypatch.setattr(main.db_service, "get_shipment", Mock(side_effect=AssertionError("sync shipment read used")))
    monkeypatch.setattr(main.twilio_service, "send_shipment_update", send_update)

    result = await main.send_shipment_sms(
        shipment.id,
        main.ShipmentSmsRequest(recipient="+15550100100", status="In transit"),
        _user={"role": "ROLE_PURCHASING"},
        session=object(),
    )

    assert result == {"status": "DRY_RUN"}
    get_shipment.assert_awaited_once_with(repositories, shipment.id)
    send_update.assert_called_once_with(
        recipient="+15550100100", shipment_id=shipment.id,
        status="In transit", tracking_url=None,
    )
