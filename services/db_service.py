import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from models.db_models import RFQ, RFQItem, InventoryItem, SupplierQuote, Quote, QuoteItem, AgentAuditLog, Supplier, Shipment, ShipmentEvent
from services.operations_store import operations_store
from services.supplier_database import supplier_db
from services.workflow_states import canonical_state, validate_transition

_inventory_lock = threading.Lock()

class MockDatabaseService:
    def __init__(self):
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
        
        if not self._restore_state():
            self.seed_mock_data()
        self.seed_supplier_records()

    @staticmethod
    def _model_data(model):
        return model.model_dump(mode="json") if hasattr(model, "model_dump") else model.dict()

    def _persist_state(self) -> None:
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
            created_at=datetime.utcnow()
        )
        self.rfqs[rfq_id] = rfq
        operations_store.upsert_customer(
            customer_id=f"CUS-{customer_email.lower()}",
            company_name=customer_name,
            contact_name=customer_name,
            email=customer_email,
        )
        operations_store.insert_rfq(
            rfq_id=rfq_id,
            customer_id=f"CUS-{customer_email.lower()}",
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
        return self.rfqs.get(rfq_id)

    def set_rfq_automation_paused(self, rfq_id: str, paused: bool, reason: Optional[str] = None) -> Optional[RFQ]:
        rfq = self.rfqs.get(rfq_id)
        if not rfq:
            return None
        rfq.automation_paused = paused
        rfq.pause_reason = reason.strip() if paused and reason else None
        self._persist_state()
        return rfq

    def list_rfqs(self) -> List[RFQ]:
        return list(self.rfqs.values())

    def update_rfq_customer(self, rfq_id: str, customer_name: Optional[str], customer_email: Optional[str]) -> Optional[RFQ]:
        rfq = self.rfqs.get(rfq_id)
        if not rfq:
            return None
        if customer_name:
            rfq.customer_name = customer_name.strip()
        if customer_email:
            rfq.customer_email = customer_email.strip().lower()
        operations_store.upsert_customer(
            customer_id=f"CUS-{rfq.customer_email.lower()}",
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
    ) -> dict:
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
        )

    def get_supplier_offers_for_part(self, part_number: str) -> List[dict]:
        return supplier_db.get_supplier_offers_for_part(part_number)

    def update_rfq_status(self, rfq_id: str, status: str, expected_version: Optional[int] = None) -> Optional[RFQ]:
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
    def add_rfq_item(self, rfq_id: str, requested_part: str, qty: int, uom: str = "EA", aircraft: str = None, condition: str = "NE") -> RFQItem:
        item_id = f"RITM-{uuid.uuid4().hex[:6].upper()}"
        item = RFQItem(
            id=item_id,
            rfq_id=rfq_id,
            requested_part_number=requested_part,
            quantity=qty,
            uom=uom,
            aircraft_type=aircraft,
            condition_preference=condition
        )
        self.rfq_items[rfq_id].append(item)
        rfq = self.rfqs.get(rfq_id)
        if rfq:
            operations_store.insert_rfq(
                rfq_id=rfq_id,
                customer_id=f"CUS-{rfq.customer_email.lower()}",
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
        return self.rfq_items.get(rfq_id, [])

    # Audit Log Operations
    def add_audit_log(self, rfq_id: str, agent_name: str, action: str, message: str, status: str = "SUCCESS", payload: str = None) -> AgentAuditLog:
        log = AgentAuditLog(
            id=len(self.audit_logs.get(rfq_id, [])) + 1,
            rfq_id=rfq_id,
            agent_name=agent_name,
            action_type=action,
            message=message,
            status=status,
            payload_json=payload,
            timestamp=datetime.utcnow()
        )
        if rfq_id not in self.audit_logs:
            self.audit_logs[rfq_id] = []
        self.audit_logs[rfq_id].append(log)
        self._persist_state()
        return log

    def get_audit_logs(self, rfq_id: str) -> List[AgentAuditLog]:
        return self.audit_logs.get(rfq_id, [])

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

    def add_quote_item(self, quote_id: str, rfq_item_id: str, part_number: str, qty: int, source: str, unit_cost: float, unit_price: float, margin: float, cert: str, comp_status: str, uom: str = "EA", attachments: Optional[List[str]] = None, description: str = "", condition: Optional[str] = None, lead_time_days: Optional[int] = None) -> QuoteItem:
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
            attachments=list(attachments or [])
        )
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
        for quote in self.quotes.values():
            if quote.rfq_id == rfq_id:
                return quote
        return None

    def get_quote(self, quote_id: str) -> Optional[Quote]:
        quote = self.quotes.get(quote_id)
        if quote and quote.valid_until and quote.status in {"Sent", "Approved"}:
            if quote.valid_until < datetime.now(timezone.utc).date().isoformat():
                quote.status = "Expired"
                supplier_db.cancel_communication_task(f"customer-followup:{quote_id}")
                self._persist_state()
        return quote

    def get_quote_items(self, quote_id: str) -> List[QuoteItem]:
        return self.quote_items.get(quote_id, [])

    def update_quote_status(self, quote_id: str, status: str, approved_by: str = None, comments: str = None, expected_version: Optional[int] = None) -> Optional[Quote]:
        if quote_id in self.quotes:
            quote = self.quotes[quote_id]
            if expected_version is not None and quote.version != expected_version:
                raise ValueError(f"Quote {quote_id} was updated by another operation.")
            quote.status = status
            if approved_by:
                quote.approved_by = approved_by
                quote.approved_at = datetime.utcnow()
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
        self.shipments[shipment_id] = shipment
        self.shipment_events[shipment_id] = []
        self.add_shipment_event(shipment_id, "Preparing Shipment", None, "Order received and awaiting fulfillment processing.")
        return shipment

    def add_shipment_event(self, shipment_id: str, status: str, location: Optional[str], description: str) -> ShipmentEvent:
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
            self.shipments[shipment_id].updated_at = datetime.utcnow()
        self._persist_state()
        return event

    def get_shipment(self, shipment_id: str) -> Optional[Shipment]:
        return self.shipments.get(shipment_id)

    def get_shipment_by_token(self, public_token: str) -> Optional[Shipment]:
        return next((shipment for shipment in self.shipments.values() if shipment.public_token == public_token), None)

    def find_shipment_by_tracking(self, carrier: str, tracking_number: str) -> Optional[Shipment]:
        normalized_carrier = (carrier or "").lower()
        return next(
            (
                shipment for shipment in self.shipments.values()
                if (shipment.carrier or "").lower() == normalized_carrier
                and shipment.tracking_number == tracking_number
            ),
            None,
        )

    def get_shipment_events(self, shipment_id: str) -> List[ShipmentEvent]:
        return self.shipment_events.get(shipment_id, [])

    def list_shipments(self) -> List[Shipment]:
        return sorted(self.shipments.values(), key=lambda shipment: shipment.updated_at, reverse=True)

    def update_shipment_tracking(self, shipment_id: str, carrier: str, tracking_number: str) -> Optional[Shipment]:
        shipment = self.shipments.get(shipment_id)
        if not shipment:
            return None
        shipment.carrier = carrier
        shipment.tracking_number = tracking_number
        shipment.updated_at = datetime.utcnow()
        self._persist_state()
        return shipment

db_service = MockDatabaseService()
