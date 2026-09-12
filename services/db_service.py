import uuid
from datetime import datetime
from typing import Dict, List, Optional
from models.db_models import RFQ, RFQItem, InventoryItem, SupplierQuote, Quote, QuoteItem, AgentAuditLog, Supplier

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
        
        self.seed_mock_data()

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

    # RFQ Operations
    def create_rfq(self, customer_name: str, customer_email: str, raw_text: str) -> RFQ:
        rfq_id = f"RFQ-{uuid.uuid4().hex[:6].upper()}"
        rfq = RFQ(
            id=rfq_id,
            customer_name=customer_name,
            customer_email=customer_email,
            status="Intake",
            raw_text=raw_text,
            created_at=datetime.utcnow()
        )
        self.rfqs[rfq_id] = rfq
        self.rfq_items[rfq_id] = []
        self.audit_logs[rfq_id] = []
        return rfq

    def get_rfq(self, rfq_id: str) -> Optional[RFQ]:
        return self.rfqs.get(rfq_id)

    def list_rfqs(self) -> List[RFQ]:
        return list(self.rfqs.values())

    def update_rfq_status(self, rfq_id: str, status: str) -> Optional[RFQ]:
        if rfq_id in self.rfqs:
            self.rfqs[rfq_id].status = status
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
        return log

    def get_audit_logs(self, rfq_id: str) -> List[AgentAuditLog]:
        return self.audit_logs.get(rfq_id, [])

    # Quote Operations
    def create_quote(self, rfq_id: str, subtotal: float, shipping: float, total: float) -> Quote:
        quote_id = f"QTE-{uuid.uuid4().hex[:6].upper()}"
        quote = Quote(
            id=quote_id,
            rfq_id=rfq_id,
            subtotal=subtotal,
            shipping_cost=shipping,
            total_amount=total,
            status="Draft"
        )
        self.quotes[quote_id] = quote
        self.quote_items[quote_id] = []
        return quote

    def add_quote_item(
        self,
        quote_id: str,
        rfq_item_id: str,
        part_number: str,
        qty: int,
        source: str,
        unit_cost: float,
        unit_price: float,
        margin: float,
        cert: str,
        comp_status: str,
        supplier_id: str = None,
        supplier_name: str = None,
    ) -> QuoteItem:
        qi_id = f"QITM-{uuid.uuid4().hex[:6].upper()}"
        item = QuoteItem(
            id=qi_id,
            quote_id=quote_id,
            rfq_item_id=rfq_item_id,
            part_number=part_number,
            quantity=qty,
            source=source,
            unit_cost=unit_cost,
            unit_price=unit_price,
            margin_percent=margin,
            certificate_type=cert,
            compliance_status=comp_status,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
        )
        if quote_id not in self.quote_items:
            self.quote_items[quote_id] = []
        self.quote_items[quote_id].append(item)
        return item

    def get_quote_by_rfq(self, rfq_id: str) -> Optional[Quote]:
        for quote in self.quotes.values():
            if quote.rfq_id == rfq_id:
                return quote
        return None

    def get_quote(self, quote_id: str) -> Optional[Quote]:
        return self.quotes.get(quote_id)

    def get_quote_items(self, quote_id: str) -> List[QuoteItem]:
        return self.quote_items.get(quote_id, [])

    def update_quote_status(self, quote_id: str, status: str, approved_by: str = None, comments: str = None) -> Optional[Quote]:
        if quote_id in self.quotes:
            quote = self.quotes[quote_id]
            quote.status = status
            if approved_by:
                quote.approved_by = approved_by
                quote.approved_at = datetime.utcnow()
            if comments:
                quote.comments = comments
            return quote
        return None

db_service = MockDatabaseService()
