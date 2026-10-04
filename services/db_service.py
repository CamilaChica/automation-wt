import json
import os
import threading
import uuid
from collections.abc import MutableMapping
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from models.db_models import RFQ, RFQItem, InventoryItem, SupplierQuote, Quote, QuoteItem, AgentAuditLog, Supplier, Shipment, ShipmentEvent
from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.workflow_states import canonical_state, validate_transition
from services.customer_chase_schedule import chase_task_keys

_inventory_lock = threading.Lock()


class _PostgresRecordMap(MutableMapping):
    def __init__(self, domain: str, model_type):
        self.domain = domain
        self.model_type = model_type

    def __getitem__(self, key):
        payload = operations_store.get_operational_record(self.domain, str(key))
        if payload is None:
            raise KeyError(key)
        return self.model_type.model_validate(payload)

    def __setitem__(self, key, value):
        operations_store.save_operational_record(self.domain, str(key), MockDatabaseService._model_data(value))

    def __delitem__(self, key):
        if operations_store.get_operational_record(self.domain, str(key)) is None:
            raise KeyError(key)
        operations_store.delete_operational_record(self.domain, str(key))

    def __iter__(self):
        return iter(operations_store.list_operational_records(self.domain))

    def __len__(self):
        return len(operations_store.list_operational_records(self.domain))

    def values(self):
        return [self.model_type.model_validate(value) for value in operations_store.list_operational_records(self.domain).values()]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

class MockDatabaseService:
    async def get_rfq_async(self, repositories, rfq_id: str) -> Optional[RFQ]:
        payload = await repositories.rfq.get_operational_record("rfqs", rfq_id)
        if payload:
            return RFQ.model_validate(payload)
        record = await repositories.rfq.get(rfq_id)
        if record is None:
            return None
        return RFQ(
            id=record.id,
            customer_name=record.customer_name,
            customer_email=record.customer_email,
            status=record.status,
            raw_text=record.raw_text,
            thread_id=record.thread_id,
            created_at=record.created_at,
        )

    async def get_shipment_async(self, repositories, shipment_id: str) -> Optional[Shipment]:
        payload = await repositories.records.get("shipments", shipment_id)
        return Shipment.model_validate(payload) if payload else None

    async def create_shipment_async(
        self, repositories, rfq_id: str, quote_id: Optional[str], customer_email: str,
        part_numbers: List[str], quantity: int, public_token: str,
    ) -> Shipment:
        shipment_id = f"SHP-{uuid.uuid4().hex[:8].upper()}"
        shipment = Shipment(
            id=shipment_id,
            rfq_id=rfq_id,
            quote_id=quote_id,
            customer_email=customer_email,
            part_numbers=part_numbers,
            quantity=quantity,
            public_token=public_token,
        )
        event = ShipmentEvent(
            id=f"SHE-{uuid.uuid4().hex[:8].upper()}",
            shipment_id=shipment_id,
            status="Preparing Shipment",
            location=None,
            description="Order received and awaiting fulfillment processing.",
        )
        shipment.updated_at = event.occurred_at
        await repositories.records.upsert(
            "shipments", shipment_id, shipment.model_dump(mode="json")
        )
        await repositories.records.upsert(
            "shipment_events", event.id, event.model_dump(mode="json")
        )
        return shipment

    async def add_shipment_event_async(
        self, repositories, shipment_id: str, status: str,
        location: Optional[str], description: str,
    ) -> Optional[ShipmentEvent]:
        shipment = await self.get_shipment_async(repositories, shipment_id)
        if shipment is None:
            return None
        event = ShipmentEvent(
            id=f"SHE-{uuid.uuid4().hex[:8].upper()}",
            shipment_id=shipment_id,
            status=status,
            location=location,
            description=description,
        )
        shipment.status = status
        shipment.updated_at = datetime.now(timezone.utc)
        await repositories.records.upsert(
            "shipments", shipment_id, shipment.model_dump(mode="json")
        )
        await repositories.records.upsert(
            "shipment_events", event.id, event.model_dump(mode="json")
        )
        return event

    async def update_shipment_tracking_async(
        self, repositories, shipment_id: str, carrier: str, tracking_number: str
    ) -> Optional[Shipment]:
        shipment = await self.get_shipment_async(repositories, shipment_id)
        if shipment is None:
            return None
        shipment.carrier = carrier
        shipment.tracking_number = tracking_number
        shipment.updated_at = datetime.now(timezone.utc)
        await repositories.records.upsert(
            "shipments", shipment_id, shipment.model_dump(mode="json")
        )
        return shipment

    async def get_shipment_by_token_async(self, repositories, public_token: str) -> Optional[Shipment]:
        records = await repositories.records.list_by_payload_value(
            "shipments", "public_token", public_token
        )
        payload = next(iter(records.values()), None)
        if not payload:
            records = await repositories.records.list_by_payload_value(
                "shipments", "tracking_number", public_token
            )
            payload = next(iter(records.values()), None)
        return Shipment.model_validate(payload) if payload else None

    async def get_shipment_events_async(self, repositories, shipment_id: str) -> List[ShipmentEvent]:
        records = await repositories.records.list_by_payload_value(
            "shipment_events", "shipment_id", shipment_id
        )
        events = [
            ShipmentEvent.model_validate(value)
            for value in records.values()
        ]
        return sorted(events, key=lambda event: event.occurred_at)

    async def list_shipments_async(self, repositories) -> List[Shipment]:
        records = await repositories.records.list("shipments")
        shipments = [Shipment.model_validate(value) for value in records.values()]
        return sorted(shipments, key=lambda shipment: shipment.updated_at, reverse=True)

    async def list_rfqs_async(self, repositories) -> List[RFQ]:
        records = await repositories.rfq.list_operational_records("rfqs")
        if records:
            rfqs = [RFQ.model_validate(payload) for payload in records.values()]
            item_records = await repositories.rfq.list_operational_records("rfq_items")
            return self._attach_part_numbers(rfqs, item_records.values())
        return [
            RFQ(
                id=record.id,
                customer_name=record.customer_name,
                customer_email=record.customer_email,
                status=record.status,
                raw_text=record.raw_text,
                thread_id=record.thread_id,
                created_at=record.created_at,
            )
            for record in await repositories.rfq.list()
        ]

    async def create_rfq_async(
        self, repositories, customer_name: str, customer_email: str,
        raw_text: str, thread_id: Optional[str] = None,
    ) -> RFQ:
        rfq = RFQ(
            id=f"RFQ-{uuid.uuid4().hex[:6].upper()}",
            customer_name=customer_name,
            customer_email=customer_email,
            status="Intake",
            raw_text=raw_text,
            thread_id=thread_id,
            created_at=datetime.now(timezone.utc),
        )
        await repositories.rfq.create_from_payload(rfq.model_dump(mode="json"))
        return rfq

    async def get_audit_logs_async(self, repositories, rfq_id: str) -> List[AgentAuditLog]:
        return [
            AgentAuditLog(
                id=record.id,
                rfq_id=record.rfq_id,
                agent_name=record.agent_name,
                action_type=record.action_type,
                message=record.message,
                status=record.status,
                payload_json=record.payload_json,
                timestamp=record.created_at,
            )
            for record in await repositories.rfq.audit_logs(rfq_id)
        ]

    def __getattr__(self, name):
        if name == "_production":
            return operations_store.storage_engine == "postgresql"
        raise AttributeError(name)

    def __init__(self):
        self._production = operations_store.storage_engine == "postgresql"
        self.rfqs: Dict[str, RFQ] = {}
        self.rfq_items: Dict[str, List[RFQItem]] = {}
        self.inventory: Dict[str, InventoryItem] = {}
        self.suppliers: Dict[str, Supplier] = {}
        self.supplier_quotes: Dict[str, List[SupplierQuote]] = {}
        self.quotes: Dict[str, Quote] = {}
        self.quote_items: Dict[str, List[QuoteItem]] = {}
        self.audit_logs: Dict[str, List[AgentAuditLog]] = {}
        self.shipments: Dict[str, Shipment] = {}
        self.shipment_events: Dict[str, List[ShipmentEvent]] = {}
        
        production = any(
            os.getenv(name, "").strip().lower() == "production"
            for name in ("ENVIRONMENT", "WT_ENV", "WT_AUTH_ENV")
        ) or os.getenv("RENDER", "false").strip().lower() in {"1", "true", "yes", "on"}
        if self._production:
            self.rfqs = _PostgresRecordMap("rfqs", RFQ)
            self.rfq_items = _PostgresRecordMap("rfq_items", RFQItem)
            self.inventory = _PostgresRecordMap("inventory", InventoryItem)
            self.suppliers = _PostgresRecordMap("suppliers", Supplier)
            self.supplier_quotes = _PostgresRecordMap("supplier_quotes", SupplierQuote)
            self.quotes = _PostgresRecordMap("quotes", Quote)
            self.quote_items = _PostgresRecordMap("quote_items", QuoteItem)
            self.audit_logs = _PostgresRecordMap("audit_logs", AgentAuditLog)
            self.shipments = _PostgresRecordMap("shipments", Shipment)
            self.shipment_events = _PostgresRecordMap("shipment_events", ShipmentEvent)
        elif not self._restore_state() and not production:
            self.seed_mock_data()
        if not production:
            self.seed_supplier_records()

    @staticmethod
    def _model_data(model):
        return model.model_dump(mode="json") if hasattr(model, "model_dump") else model.dict()

    def _persist_state(self) -> None:
        if self._production:
            raise RuntimeError("Whole-state snapshots are disabled for production PostgreSQL persistence.")
        operations_store.save({
            "rfqs": {key: self._model_data(value) for key, value in self.rfqs.items()},
            "rfq_items": {key: [self._model_data(value) for value in values] for key, values in self.rfq_items.items()},
            "inventory": {key: self._model_data(value) for key, value in self.inventory.items()},
            "suppliers": {key: self._model_data(value) for key, value in self.suppliers.items()},
            "quotes": {key: self._model_data(value) for key, value in self.quotes.items()},
            "quote_items": {key: [self._model_data(value) for value in values] for key, values in self.quote_items.items()},
            "audit_logs": {key: [self._model_data(value) for value in values] for key, values in self.audit_logs.items()},
            "shipments": {key: self._model_data(value) for key, value in self.shipments.items()},
            "shipment_events": {key: [self._model_data(value) for value in values] for key, values in self.shipment_events.items()},
        })

    def _pg_record(self, domain: str, record_id: str, model):
        if model is None:
            return None
        operations_store.save_operational_record(domain, record_id, self._model_data(model))
        return model

    def _pg_get(self, domain: str, record_id: str, model_type):
        payload = operations_store.get_operational_record(domain, record_id)
        return model_type.model_validate(payload) if payload is not None else None

    def _pg_list(self, domain: str, model_type):
        return [model_type.model_validate(payload) for payload in operations_store.list_operational_records(domain).values()]

    @staticmethod
    def _customer_record_id(email: str) -> str:
        normalized = email.strip().lower()
        candidate = f"CUS-{normalized}"
        return candidate if len(candidate) <= 64 else f"CUS-{uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:32].upper()}"

    def _restore_state(self) -> bool:
        state = operations_store.load()
        if not state:
            return False
        self.rfqs = {key: RFQ.model_validate(value) for key, value in state.get("rfqs", {}).items()}
        for rfq in self.rfqs.values():
            rfq.workflow_state = canonical_state(rfq.status)
        self.rfq_items = {key: [RFQItem.model_validate(item) for item in values] for key, values in state.get("rfq_items", {}).items()}
        self.inventory = {key: InventoryItem.model_validate(value) for key, value in state.get("inventory", {}).items()}
        self.suppliers = {key: Supplier.model_validate(value) for key, value in state.get("suppliers", {}).items()}
        self.quotes = {key: Quote.model_validate(value) for key, value in state.get("quotes", {}).items()}
        self.quote_items = {key: [QuoteItem.model_validate(item) for item in values] for key, values in state.get("quote_items", {}).items()}
        self.audit_logs = {key: [AgentAuditLog.model_validate(item) for item in values] for key, values in state.get("audit_logs", {}).items()}
        self.shipments = {key: Shipment.model_validate(value) for key, value in state.get("shipments", {}).items()}
        self.shipment_events = {key: [ShipmentEvent.model_validate(item) for item in values] for key, values in state.get("shipment_events", {}).items()}
        return True

    def seed_supplier_records(self):
        relevant_suppliers = [
            {"supplier_name": "Apex Aero Components LLC", "supplier_email": "quotes@apexaero.com", "part_number": "060-1234-00", "quantity_available": 10, "unit_cost": 1100.0, "certificate_type": "FAA 8130-3", "lead_time_days": 3, "approval_status": "Approved", "condition_code": "NE"},
            {"supplier_name": "Vanguard Aviation Spares Inc.", "supplier_email": "procurement@vanguardspares.com", "part_number": "060-1234-00", "quantity_available": 3, "unit_cost": 1050.0, "certificate_type": "FAA 8130-3", "lead_time_days": 7, "approval_status": "Approved", "condition_code": "NE"},
            {"supplier_name": "Horizon MRO Parts Ltd.", "supplier_email": "sales@horizonmro.com", "part_number": "456-789-OH", "quantity_available": 5, "unit_cost": 500.0, "certificate_type": "FAA 8130-3", "lead_time_days": 2, "approval_status": "Approved", "condition_code": "OH"},
        ]
        for offer in relevant_suppliers:
            supplier_db.save_supplier_offer(
                supplier_name=offer["supplier_name"],
                supplier_email=offer["supplier_email"],
                part_number=offer["part_number"],
                quantity_available=offer["quantity_available"],
                unit_cost=offer["unit_cost"],
                certificate_type=offer["certificate_type"],
                lead_time_days=offer["lead_time_days"],
                approval_status=offer["approval_status"],
                condition_code=offer["condition_code"],
                trace_documents=[offer["certificate_type"]],
                source_received_at=datetime.now(timezone.utc),
            )

    def reset_supplier_data(self):
        supplier_db.reset_supplier_data()
        self.seed_supplier_records()

    def seed_mock_data(self):
        # 1. Seed Inventory
        items = [
            InventoryItem(
                id="INV-001",
                part_number="060-1234-00",
                serial_number="SN-WR-001",
                quantity_available=1,
                condition_code="NE",
                warehouse_location="Aisle 3, Bin B4",
                unit_cost=1000.00,
                certificate_type="FAA 8130-3",
                has_full_trace=True
            ),
            InventoryItem(
                id="INV-002",
                part_number="060-1234-00",
                serial_number="SN-WR-002",
                quantity_available=1,
                condition_code="NE",
                warehouse_location="Aisle 3, Bin B5",
                unit_cost=1000.00,
                certificate_type="FAA 8130-3",
                has_full_trace=True
            ),
            InventoryItem(
                id="INV-003",
                part_number="456-789-OH",
                serial_number="SN-ACT-981",
                quantity_available=1,
                condition_code="OH",
                warehouse_location="Aisle 12, Bin C1",
                unit_cost=450.00,
                certificate_type="EASA Form 1",
                has_full_trace=True
            ),
            InventoryItem(
                id="INV-004",
                part_number="456-789-OH",
                serial_number="SN-ACT-982",
                quantity_available=1,
                condition_code="OH",
                warehouse_location="Aisle 12, Bin C2",
                unit_cost=450.00,
                certificate_type="FAA 8130-3",
                has_full_trace=False # Missing trace history
            )
        ]
        for item in items:
            self.inventory[item.id] = item

        # 2. Seed Suppliers
        suppliers_data = [
            Supplier(
                id="SUP-001",
                company_name="Apex Aero Components LLC",
                dba_name="Apex Aero",
                contact_name="Robert Hartwell",
                contact_title="Director of Sales",
                phone="+1-305-555-0142",
                phone_alt="+1-305-555-0199",
                email="r.hartwell@apexaero.com",
                email_quotes="quotes@apexaero.com",
                website="https://www.apexaerocomponents.com",
                address_line1="4521 NW 36th Street",
                address_line2="Suite 210",
                city="Miami",
                state_province="FL",
                postal_code="33166",
                country="US",
                approval_status="Approved",
                itar_certified=True,
                account_manager="Sarah Liu",
                notes="Preferred Boeing parts supplier."
            ),
            Supplier(
                id="SUP-002",
                company_name="Vanguard Aviation Spares Inc.",
                contact_name="Maria Fontaine",
                contact_title="Procurement Manager",
                phone="+1-972-555-0378",
                email="m.fontaine@vanguardspares.com",
                email_quotes="procurement@vanguardspares.com",
                website="https://www.vanguardspares.com",
                address_line1="7800 Sovereign Row",
                city="Dallas",
                state_province="TX",
                postal_code="75247",
                country="US",
                approval_status="Approved",
                itar_certified=True,
                account_manager="Sarah Liu"
            )
        ]
        for sup in suppliers_data:
            self.suppliers[sup.id] = sup
        self._persist_state()
        self._persist_state()

    def reserve_inventory(self, part_number: str, quantity: int) -> bool:
        if quantity < 1:
            raise ValueError("Reservation quantity must be positive.")
        if self._production:
            return operations_store.reserve_inventory(part_number, quantity)
        with _inventory_lock:
            matching = sorted(
                (item for item in self.inventory.values() if item.part_number.upper() == part_number.upper()),
                key=lambda item: item.id,
            )
            if sum(item.quantity_available for item in matching) < quantity:
                return False
            remaining = quantity
            for item in matching:
                allocation = min(item.quantity_available, remaining)
                item.quantity_available -= allocation
                remaining -= allocation
                if remaining == 0:
                    break
            self._persist_state()
            return True

    # RFQ Operations
    def create_rfq(self, customer_name: str, customer_email: str, raw_text: str, thread_id: Optional[str] = None) -> RFQ:
        rfq_id = f"RFQ-{uuid.uuid4().hex[:6].upper()}"
        rfq = RFQ(
            id=rfq_id,
            customer_name=customer_name,
            customer_email=customer_email,
            status="Intake",
            raw_text=raw_text,
            thread_id=thread_id,
            created_at=datetime.now(timezone.utc)
        )
        if self._production:
            customer_id = self._customer_record_id(customer_email)
            with operations_store.transaction():
                operations_store.upsert_customer(customer_id, customer_name, customer_name, customer_email)
                operations_store.insert_rfq(
                    rfq_id=rfq_id, customer_id=customer_id, part_number=None, description=raw_text[:500],
                    quantity=1, condition=None, certification=None, destination=None, status=rfq.status,
                    raw_text=raw_text, thread_id=thread_id,
                )
                self._pg_record("rfqs", rfq_id, rfq)
            return rfq
        self.rfqs[rfq_id] = rfq
        operations_store.upsert_customer(
            customer_id=self._customer_record_id(customer_email),
            company_name=customer_name,
            contact_name=customer_name,
            email=customer_email,
        )
        operations_store.insert_rfq(
            rfq_id=rfq_id,
            customer_id=self._customer_record_id(customer_email),
            part_number=None,
            description=raw_text[:500],
            quantity=1,
            condition=None,
            certification=None,
            destination=None,
            status=rfq.status,
            raw_text=raw_text,
            thread_id=thread_id,
        )
        self.rfq_items[rfq_id] = []
        self.audit_logs[rfq_id] = []
        self._persist_state()
        return rfq

    def get_rfq(self, rfq_id: str) -> Optional[RFQ]:
        if self._production:
            return self._pg_get("rfqs", rfq_id, RFQ)
        return self.rfqs.get(rfq_id)

    def set_rfq_automation_paused(self, rfq_id: str, paused: bool, reason: Optional[str] = None) -> Optional[RFQ]:
        if self._production:
            rfq = self.get_rfq(rfq_id)
            if not rfq:
                return None
            rfq.automation_paused = paused
            rfq.pause_reason = reason.strip() if paused and reason else None
            return self._pg_record("rfqs", rfq_id, rfq)
        rfq = self.rfqs.get(rfq_id)
        if not rfq:
            return None
        rfq.automation_paused = paused
        rfq.pause_reason = reason.strip() if paused and reason else None
        self._persist_state()
        return rfq

    @staticmethod
    def _attach_part_numbers(rfqs: List[RFQ], items) -> List[RFQ]:
        parts_by_rfq: dict[str, list[str]] = {}
        flat = []
        for entry in items:
            flat.extend(entry if isinstance(entry, (list, tuple)) else [entry])
        for item in flat:
            if not isinstance(item, dict):
                item = item.model_dump() if hasattr(item, "model_dump") else vars(item)
            part = str(
                item.get("resolved_part_number")
                or item.get("requested_part_number")
                or item.get("part_number")
                or ""
            ).strip()
            parts = parts_by_rfq.setdefault(str(item.get("rfq_id")), [])
            if part and part not in parts:
                parts.append(part)
        for rfq in rfqs:
            if not rfq.part_number and parts_by_rfq.get(rfq.id):
                rfq.part_number = ", ".join(parts_by_rfq[rfq.id])
        return rfqs

    def list_rfqs(self) -> List[RFQ]:
        if self._production:
            rfqs = self._pg_list("rfqs", RFQ)
            items = operations_store.list_operational_records("rfq_items").values()
            return self._attach_part_numbers(rfqs, items)
        return self._attach_part_numbers(list(self.rfqs.values()), getattr(self, "rfq_items", {}).values())

    def update_rfq_customer(self, rfq_id: str, customer_name: Optional[str], customer_email: Optional[str]) -> Optional[RFQ]:
        if self._production:
            rfq = self.get_rfq(rfq_id)
            if not rfq:
                return None
            if customer_name:
                rfq.customer_name = customer_name.strip()
            if customer_email:
                rfq.customer_email = customer_email.strip().lower()
            with operations_store.transaction():
                operations_store.upsert_customer(
                    self._customer_record_id(rfq.customer_email), rfq.customer_name, rfq.customer_name, rfq.customer_email
                )
                self._pg_record("rfqs", rfq_id, rfq)
            return rfq
        rfq = self.rfqs.get(rfq_id)
        if not rfq:
            return None
        if customer_name:
            rfq.customer_name = customer_name.strip()
        if customer_email:
            rfq.customer_email = customer_email.strip().lower()
        operations_store.upsert_customer(
            customer_id=self._customer_record_id(rfq.customer_email),
            company_name=rfq.customer_name,
            contact_name=rfq.customer_name,
            email=rfq.customer_email,
        )
        self._persist_state()
        return rfq

    def save_supplier_offer(
        self,
        supplier_name: str,
        supplier_email: Optional[str] = None,
        part_number: str = "",
        quantity_available: Optional[int] = None,
        unit_cost: Optional[float] = None,
        certificate_type: Optional[str] = None,
        lead_time_days: Optional[int] = None,
        approval_status: str = "Pending",
        condition_code: Optional[str] = None,
        source_email_id: Optional[str] = None,
        confidence: float = 1.0,
        source_received_at: Optional[datetime] = None,
    ) -> dict:
        if self._production:
            return operations_store.save_supplier_offer(
                supplier_name=supplier_name, supplier_email=supplier_email,
                part_number=part_number, quantity_available=quantity_available,
                unit_cost=unit_cost, certificate_type=certificate_type,
                lead_time_days=lead_time_days, approval_status=approval_status,
                condition_code=condition_code, source_email_id=source_email_id,
                confidence=confidence,
                source_received_at=source_received_at,
            )
        return supplier_db.save_supplier_offer(
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            part_number=part_number,
            quantity_available=quantity_available,
            unit_cost=unit_cost,
            certificate_type=certificate_type,
            lead_time_days=lead_time_days,
            approval_status=approval_status,
            condition_code=condition_code,
            source_email_id=source_email_id,
            confidence=confidence,
            source_received_at=source_received_at,
        )

    def get_supplier_offers_for_part(self, part_number: str) -> List[dict]:
        if self._production:
            return operations_store.get_supplier_offers(part_number)
        return supplier_db.get_supplier_offers_for_part(part_number)

    def update_rfq_status(self, rfq_id: str, status: str, expected_version: Optional[int] = None) -> Optional[RFQ]:
        if self._production:
            with operations_store.transaction():
                payload = operations_store.lock_operational_record("rfqs", rfq_id)
                if payload is None:
                    return None
                rfq = RFQ.model_validate(payload)
                if expected_version is not None and rfq.version != expected_version:
                    raise ValueError(f"RFQ {rfq_id} was updated by another operation.")
                validate_transition(rfq.status, status)
                rfq.status = status
                rfq.workflow_state = canonical_state(status)
                rfq.version += 1
                operations_store.update_rfq_status(rfq_id, status)
                self._pg_record("rfqs", rfq_id, rfq)
            return rfq
        if rfq_id in self.rfqs:
            if expected_version is not None and self.rfqs[rfq_id].version != expected_version:
                raise ValueError(f"RFQ {rfq_id} was updated by another operation.")
            current_status = self.rfqs[rfq_id].status
            validate_transition(current_status, status)
            self.rfqs[rfq_id].status = status
            self.rfqs[rfq_id].workflow_state = canonical_state(status)
            self.rfqs[rfq_id].version += 1
            operations_store.update_rfq_status(rfq_id, status)
            self._persist_state()
            return self.rfqs[rfq_id]
        return None

    # RFQ Items Operations
    def add_rfq_item(
        self,
        rfq_id: str,
        requested_part: str,
        qty: int,
        uom: str = "EA",
        aircraft: str = None,
        condition: str = "NE",
        description: Optional[str] = None,
        target_price: Optional[float] = None,
        currency: Optional[str] = None,
    ) -> RFQItem:
        item_id = f"RITM-{uuid.uuid4().hex[:6].upper()}"
        item = RFQItem(
            id=item_id,
            rfq_id=rfq_id,
            requested_part_number=requested_part,
            quantity=qty,
            uom=uom,
            aircraft_type=aircraft,
            condition_preference=condition,
            description=description,
            target_price=target_price,
            currency=currency,
        )
        if self._production:
            if not self.get_rfq(rfq_id):
                raise ValueError(f"RFQ {rfq_id} not found.")
            self._pg_record("rfq_items", item.id, item)
            rfq = self.get_rfq(rfq_id)
            operations_store.insert_rfq(
                rfq_id=rfq_id, customer_id=self._customer_record_id(rfq.customer_email),
                part_number=requested_part, description=rfq.raw_text[:500], quantity=qty,
                condition=condition, certification=None, destination=None, status=rfq.status,
                raw_text=rfq.raw_text, thread_id=rfq.thread_id,
            )
            return item
        self.rfq_items[rfq_id].append(item)
        rfq = self.rfqs.get(rfq_id)
        if rfq:
            operations_store.insert_rfq(
                rfq_id=rfq_id,
                customer_id=self._customer_record_id(rfq.customer_email),
                part_number=requested_part,
                description=rfq.raw_text[:500],
                quantity=qty,
                condition=condition,
                certification=None,
                destination=None,
                status=rfq.status,
                raw_text=rfq.raw_text,
                thread_id=rfq.thread_id,
            )
        self._persist_state()
        return item

    def get_rfq_items(self, rfq_id: str) -> List[RFQItem]:
        if self._production:
            return [item for item in self._pg_list("rfq_items", RFQItem) if item.rfq_id == rfq_id]
        return self.rfq_items.get(rfq_id, [])

    def resolve_rfq_item(self, item_id: str, resolved_part_number: str) -> Optional[RFQItem]:
        part_number = str(resolved_part_number or "").strip().upper()
        if not part_number:
            raise ValueError("Resolved part number is required.")
        if self._production:
            item = self._pg_get("rfq_items", item_id, RFQItem)
            if item is None:
                return None
            item.resolved_part_number = part_number
            return self._pg_record("rfq_items", item_id, item)
        for items in self.rfq_items.values():
            for item in items:
                if item.id == item_id:
                    item.resolved_part_number = part_number
                    self._persist_state()
                    return item
        return None

    def replace_rfq_items(self, rfq_id: str, items: List[Dict[str, Any]]) -> List[RFQItem]:
        if self._production:
            if not self.get_rfq(rfq_id):
                raise ValueError(f"RFQ {rfq_id} not found.")
            with operations_store.transaction():
                for existing_item in self.get_rfq_items(rfq_id):
                    operations_store.delete_operational_record("rfq_items", existing_item.id)
                return [
                    self.add_rfq_item(
                        rfq_id, str(item["part_number"]), int(item["quantity"]),
                        uom=str(item.get("unit_of_measure") or "EA"),
                        condition=str(item.get("condition_code") or "NE"),
                        description=item.get("description"),
                        target_price=item.get("target_price"),
                        currency=item.get("currency"),
                    )
                    for item in items
                ]
        if rfq_id not in self.rfqs:
            raise ValueError(f"RFQ {rfq_id} not found.")
        self.rfq_items[rfq_id] = []
        replaced = [
            self.add_rfq_item(
                rfq_id,
                str(item["part_number"]),
                int(item["quantity"]),
                uom=str(item.get("unit_of_measure") or "EA"),
                condition=str(item.get("condition_code") or "NE"),
                description=item.get("description"),
                target_price=item.get("target_price"),
                currency=item.get("currency"),
            )
            for item in items
        ]
        self._persist_state()
        return replaced

    # Audit Log Operations
    def add_audit_log(self, rfq_id: str, agent_name: str, action: str, message: str, status: str = "SUCCESS", payload: str = None) -> AgentAuditLog:
        log = AgentAuditLog(
            rfq_id=rfq_id,
            agent_name=agent_name,
            action_type=action,
            message=message,
            status=status,
            payload_json=payload,
            timestamp=datetime.now(timezone.utc)
        )
        persisted = operations_store.insert_audit_log(
            rfq_id=rfq_id, agent_name=agent_name, action_type=action, message=message,
            status=status, payload_json=payload, timestamp=log.timestamp,
        )
        return log.model_copy(update=persisted)

    def get_audit_logs(self, rfq_id: str) -> List[AgentAuditLog]:
        return [AgentAuditLog.model_validate(log) for log in operations_store.list_audit_logs(rfq_id)]

    # Quote Operations
    def create_quote(
        self,
        rfq_id: str,
        subtotal: float,
        shipping: float,
        total: float,
        lead_time_days: Optional[int] = None,
        valid_until: Optional[str] = None,
    ) -> Quote:
        quote_id = f"QTE-{uuid.uuid4().hex[:6].upper()}"
        quote = Quote(
            id=quote_id,
            rfq_id=rfq_id,
            subtotal=subtotal,
            shipping_cost=shipping,
            total_amount=total,
            lead_time_days=lead_time_days,
            valid_until=valid_until,
            status="Draft"
        )
        if self._production:
            if not self.get_rfq(rfq_id):
                raise ValueError(f"RFQ {rfq_id} not found.")
            with operations_store.transaction():
                self._pg_record("quotes", quote_id, quote)
                operations_store.insert_customer_quote(
                    quote_id=quote_id, rfq_id=rfq_id, unit_price=0.0, quantity=1,
                    total_price=total, lead_time=lead_time_days, condition=None,
                    certification=None, valid_until=valid_until, status=quote.status,
                )
            return quote
        self.quotes[quote_id] = quote
        self.quote_items[quote_id] = []
        operations_store.insert_customer_quote(
            quote_id=quote_id,
            rfq_id=rfq_id,
            unit_price=0.0,
            quantity=1,
            total_price=total,
            lead_time=lead_time_days,
            condition=None,
            certification=None,
            valid_until=valid_until,
            status=quote.status,
        )
        self._persist_state()
        return quote

    def add_quote_item(self, quote_id: str, rfq_item_id: str, part_number: str, qty: int, source: str, unit_cost: float, unit_price: float, margin: float, cert: str, comp_status: str, uom: str = "EA", attachments: Optional[List[str]] = None, description: str = "", condition: Optional[str] = None, lead_time_days: Optional[int] = None, source_email_id: Optional[str] = None, warranty_terms: Optional[str] = None, trace_documents: Optional[List[str]] = None) -> QuoteItem:
        qi_id = f"QITM-{uuid.uuid4().hex[:6].upper()}"
        item = QuoteItem(
            id=qi_id,
            quote_id=quote_id,
            rfq_item_id=rfq_item_id,
            part_number=part_number,
            description=description or part_number,
            quantity=qty,
            uom=uom,
            source=source,
            unit_cost=unit_cost,
            unit_price=unit_price,
            margin_percent=margin,
            certificate_type=cert,
            condition=condition,
            lead_time_days=lead_time_days,
            compliance_status=comp_status,
            attachments=list(attachments or []),
            source_email_id=source_email_id,
            warranty_terms=warranty_terms,
            trace_documents=list(trace_documents or []),
        )
        if self._production:
            quote = self.get_quote(quote_id)
            if not quote:
                raise ValueError(f"Quote {quote_id} not found.")
            with operations_store.transaction():
                self._pg_record("quote_items", qi_id, item)
                operations_store.insert_customer_quote(
                    quote_id=quote_id, rfq_id=quote.rfq_id, unit_price=unit_price, quantity=qty,
                    total_price=quote.total_amount, lead_time=lead_time_days, condition=condition,
                    certification=cert, valid_until=quote.valid_until, status=quote.status,
                )
                operations_store.insert_customer_quote_item(
                    item_id=qi_id, quote_id=quote_id, rfq_item_id=rfq_item_id, part_number=part_number,
                    description=description or part_number, quantity=qty, condition=condition,
                    certification=cert, unit_price=unit_price, lead_time=lead_time_days,
                    attachments=json.dumps(list(attachments or [])),
                )
            return item
        if quote_id not in self.quote_items:
            self.quote_items[quote_id] = []
        self.quote_items[quote_id].append(item)
        quote = self.quotes.get(quote_id)
        if quote:
            operations_store.insert_customer_quote(
                quote_id=quote_id,
                rfq_id=quote.rfq_id,
                unit_price=unit_price,
                quantity=qty,
                total_price=quote.total_amount,
                lead_time=lead_time_days,
                condition=condition,
                certification=cert,
                valid_until=quote.valid_until,
                status=quote.status,
            )
            operations_store.insert_customer_quote_item(
                item_id=qi_id,
                quote_id=quote_id,
                rfq_item_id=rfq_item_id,
                part_number=part_number,
                description=description or part_number,
                quantity=qty,
                condition=condition,
                certification=cert,
                unit_price=unit_price,
                lead_time=lead_time_days,
                attachments=json.dumps(list(attachments or [])),
            )
        self._persist_state()
        return item

    def get_quote_by_rfq(self, rfq_id: str) -> Optional[Quote]:
        if self._production:
            return next((quote for quote in self._pg_list("quotes", Quote) if quote.rfq_id == rfq_id), None)
        for quote in self.quotes.values():
            if quote.rfq_id == rfq_id:
                return quote
        return None

    def get_quote(self, quote_id: str) -> Optional[Quote]:
        if self._production:
            quote = self._pg_get("quotes", quote_id, Quote)
            if quote and quote.valid_until and quote.status in {"Sent", "Approved"}:
                if quote.valid_until < datetime.now(timezone.utc).date().isoformat():
                    quote.status = "Expired"
                    with operations_store.transaction():
                        self._pg_record("quotes", quote_id, quote)
                        operations_store.update_customer_quote_status(quote_id, "Expired")
                        for task_key in chase_task_keys(quote_id):
                            operations_store.cancel_communication_task(task_key)
            return quote
        quote = self.quotes.get(quote_id)
        if quote and quote.valid_until and quote.status in {"Sent", "Approved"}:
            if quote.valid_until < datetime.now(timezone.utc).date().isoformat():
                quote.status = "Expired"
                for task_key in chase_task_keys(quote_id):
                    supplier_db.cancel_communication_task(task_key)
                self._persist_state()
        return quote

    def get_quote_items(self, quote_id: str) -> List[QuoteItem]:
        if self._production:
            return [item for item in self._pg_list("quote_items", QuoteItem) if item.quote_id == quote_id]
        return self.quote_items.get(quote_id, [])

    def update_quote_status(self, quote_id: str, status: str, approved_by: str = None, comments: str = None, expected_version: Optional[int] = None) -> Optional[Quote]:
        if self._production:
            with operations_store.transaction():
                payload = operations_store.lock_operational_record("quotes", quote_id)
                if payload is None:
                    return None
                quote = Quote.model_validate(payload)
                if expected_version is not None and quote.version != expected_version:
                    raise ValueError(f"Quote {quote_id} was updated by another operation.")
                quote.status = status
                if approved_by:
                    quote.approved_by = approved_by
                    quote.approved_at = datetime.now(timezone.utc)
                if comments:
                    quote.comments = comments
                quote.version += 1
                self._pg_record("quotes", quote_id, quote)
                operations_store.update_customer_quote_status(quote_id, status)
            return quote
        with _inventory_lock:
            if quote_id in self.quotes:
                quote = self.quotes[quote_id]
                if expected_version is not None and quote.version != expected_version:
                    raise ValueError(f"Quote {quote_id} was updated by another operation.")
                quote.status = status
                if approved_by:
                    quote.approved_by = approved_by
                    quote.approved_at = datetime.now(timezone.utc)
                if comments:
                    quote.comments = comments
                quote.version += 1
                self._persist_state()
                return quote
        return None

    def create_shipment(self, rfq_id: str, quote_id: Optional[str], customer_email: str, part_numbers: List[str], quantity: int, public_token: str) -> Shipment:
        shipment_id = f"SHP-{uuid.uuid4().hex[:8].upper()}"
        shipment = Shipment(
            id=shipment_id,
            rfq_id=rfq_id,
            quote_id=quote_id,
            customer_email=customer_email,
            part_numbers=part_numbers,
            quantity=quantity,
            public_token=public_token,
        )
        if self._production:
            with operations_store.transaction():
                self._pg_record("shipments", shipment_id, shipment)
                self.add_shipment_event(shipment_id, "Preparing Shipment", None, "Order received and awaiting fulfillment processing.")
            return self.get_shipment(shipment_id)
        self.shipments[shipment_id] = shipment
        self.shipment_events[shipment_id] = []
        self.add_shipment_event(shipment_id, "Preparing Shipment", None, "Order received and awaiting fulfillment processing.")
        return shipment

    def add_shipment_event(self, shipment_id: str, status: str, location: Optional[str], description: str) -> ShipmentEvent:
        if self._production:
            shipment = self.get_shipment(shipment_id)
            if not shipment:
                raise ValueError(f"Shipment {shipment_id} not found.")
            event = ShipmentEvent(
                id=f"SHE-{uuid.uuid4().hex[:8].upper()}", shipment_id=shipment_id,
                status=status, location=location, description=description,
            )
            shipment.status = status
            shipment.updated_at = datetime.now(timezone.utc)
            with operations_store.transaction():
                self._pg_record("shipments", shipment_id, shipment)
                self._pg_record("shipment_events", event.id, event)
            return event
        event = ShipmentEvent(
            id=f"SHE-{uuid.uuid4().hex[:8].upper()}",
            shipment_id=shipment_id,
            status=status,
            location=location,
            description=description,
        )
        self.shipment_events.setdefault(shipment_id, []).append(event)
        if shipment_id in self.shipments:
            self.shipments[shipment_id].status = status
            self.shipments[shipment_id].updated_at = datetime.now(timezone.utc)
        self._persist_state()
        return event

    def get_shipment(self, shipment_id: str) -> Optional[Shipment]:
        if self._production:
            return self._pg_get("shipments", shipment_id, Shipment)
        return self.shipments.get(shipment_id)

    def get_shipment_by_token(self, public_token: str) -> Optional[Shipment]:
        if self._production:
            shipments = self._pg_list("shipments", Shipment)
        else:
            shipments = list(self.shipments.values())
        return next((shipment for shipment in shipments if shipment.public_token == public_token), None) or next(
            (shipment for shipment in shipments if shipment.tracking_number and shipment.tracking_number == public_token), None
        )

    def find_shipment_by_tracking(self, carrier: str, tracking_number: str) -> Optional[Shipment]:
        normalized_carrier = (carrier or "").lower()
        if self._production:
            return next((
                shipment for shipment in self._pg_list("shipments", Shipment)
                if (shipment.carrier or "").lower() == normalized_carrier
                and shipment.tracking_number == tracking_number
            ), None)
        return next(
            (
                shipment for shipment in self.shipments.values()
                if (shipment.carrier or "").lower() == normalized_carrier
                and shipment.tracking_number == tracking_number
            ),
            None,
        )

    def get_shipment_events(self, shipment_id: str) -> List[ShipmentEvent]:
        if self._production:
            return sorted(
                (event for event in self._pg_list("shipment_events", ShipmentEvent) if event.shipment_id == shipment_id),
                key=lambda event: event.occurred_at,
            )
        return self.shipment_events.get(shipment_id, [])

    def list_shipments(self) -> List[Shipment]:
        if self._production:
            return sorted(self._pg_list("shipments", Shipment), key=lambda shipment: shipment.updated_at, reverse=True)
        return sorted(self.shipments.values(), key=lambda shipment: shipment.updated_at, reverse=True)

    def update_shipment_tracking(self, shipment_id: str, carrier: str, tracking_number: str) -> Optional[Shipment]:
        if self._production:
            shipment = self.get_shipment(shipment_id)
            if not shipment:
                return None
            shipment.carrier = carrier
            shipment.tracking_number = tracking_number
            shipment.updated_at = datetime.now(timezone.utc)
            return self._pg_record("shipments", shipment_id, shipment)
        shipment = self.shipments.get(shipment_id)
        if not shipment:
            return None
        shipment.carrier = carrier
        shipment.tracking_number = tracking_number
        shipment.updated_at = datetime.now(timezone.utc)
        self._persist_state()
        return shipment

db_service = MockDatabaseService()
