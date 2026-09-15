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

    def get_supplier_by_email(self, supplier_email: str) -> Optional[Supplier]:
        normalized = supplier_email.strip().lower()
        for supplier in self.suppliers.values():
            if supplier.email.lower() == normalized:
                return supplier
            if supplier.email_quotes and supplier.email_quotes.lower() == normalized:
                return supplier
        return None

    def get_or_create_supplier_by_email(self, supplier_email: str) -> Supplier:
        existing = self.get_supplier_by_email(supplier_email)
        if existing:
            return existing

        supplier_id = f"SUP-{uuid.uuid4().hex[:6].upper()}"
        local_part = supplier_email.split("@", 1)[0].replace(".", " ").replace("-", " ").replace("_", " ").title()
        supplier = Supplier(
            id=supplier_id,
            company_name=f"{local_part} Aviation",
            contact_name=local_part or "Supplier Contact",
            phone="+1-000-000-0000",
            email=supplier_email.lower(),
            email_quotes=supplier_email.lower(),
            address_line1="Unknown",
            city="Unknown",
            state_province="NA",
            postal_code="00000",
            country="US",
            approval_status="Approved",
        )
        self.suppliers[supplier_id] = supplier
        return supplier

    def upsert_inventory_item_by_part_condition(
        self,
        *,
        part_number: str,
        condition_code: str,
        unit_cost: float,
        quantity_available: int,
        certificate_type: str,
        supplier_id: Optional[str] = None,
        lead_time_days: Optional[int] = None,
    ) -> InventoryItem:
        del supplier_id
        del lead_time_days
        for item in self.inventory.values():
            if item.part_number == part_number and item.condition_code == condition_code:
                item.unit_cost = unit_cost
                item.quantity_available = quantity_available
                item.certificate_type = certificate_type
                return item

        inventory_id = f"INV-{uuid.uuid4().hex[:6].upper()}"
        new_item = InventoryItem(
            id=inventory_id,
            part_number=part_number,
            serial_number=f"AUTO-{uuid.uuid4().hex[:8].upper()}",
            quantity_available=quantity_available,
            condition_code=condition_code,
            warehouse_location="Supplier feed",
            unit_cost=unit_cost,
            certificate_type=certificate_type,
            has_full_trace=certificate_type.upper() in {"FAA 8130-3", "EASA FORM 1", "DUAL RELEASE"},
        )
        self.inventory[new_item.id] = new_item
        return new_item

    def get_available_quantity(self, part_number: str, condition_code: Optional[str] = None) -> int:
        quantity = 0
        for item in self.inventory.values():
            if item.part_number != part_number:
                continue
            if condition_code and item.condition_code != condition_code:
                continue
            quantity += item.quantity_available
        return quantity

    def get_lowest_inventory_unit_cost(self, part_number: str, condition_code: Optional[str] = None) -> Optional[float]:
        costs: List[float] = []
        for item in self.inventory.values():
            if item.part_number != part_number:
                continue
            if condition_code and item.condition_code != condition_code:
                continue
            costs.append(item.unit_cost)
        return min(costs) if costs else None

    def get_inventory_items_for_part(self, part_number: str, condition_code: Optional[str] = None) -> List[InventoryItem]:
        matches: List[InventoryItem] = []
        for item in self.inventory.values():
            if item.part_number != part_number:
                continue
            if condition_code and item.condition_code != condition_code:
                continue
            matches.append(item)
        return matches

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

    def add_supplier_quote(self, supplier_quote: SupplierQuote) -> SupplierQuote:
        if supplier_quote.rfq_item_id not in self.supplier_quotes:
            self.supplier_quotes[supplier_quote.rfq_item_id] = []

        for index, existing in enumerate(self.supplier_quotes[supplier_quote.rfq_item_id]):
            if existing.id == supplier_quote.id:
                self.supplier_quotes[supplier_quote.rfq_item_id][index] = supplier_quote
                return supplier_quote

        self.supplier_quotes[supplier_quote.rfq_item_id].append(supplier_quote)
        return supplier_quote

    def create_supplier_quote_request(
        self,
        *,
        rfq_item_id: str,
        supplier_id: str,
        supplier_name: str,
        contact_email: str,
        part_number: str,
        quantity_available: int,
        status: str = "PENDING_SUPPLIER_RESPONSE",
        unit_cost: float = 0.0,
        lead_time_days: int = 0,
        certificate_type: str = "Unknown",
    ) -> SupplierQuote:
        quote = SupplierQuote(
            id=f"SQ-{uuid.uuid4().hex[:6].upper()}",
            rfq_item_id=rfq_item_id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            contact_email=contact_email,
            part_number=part_number,
            unit_cost=unit_cost,
            quantity_available=quantity_available,
            lead_time_days=lead_time_days,
            certificate_type=certificate_type,
            status=status,
        )
        return self.add_supplier_quote(quote)

    def list_pending_supplier_quotes(self) -> List[SupplierQuote]:
        pending: List[SupplierQuote] = []
        for quotes in self.supplier_quotes.values():
            for quote in quotes:
                if quote.status == "PENDING_SUPPLIER_RESPONSE":
                    pending.append(quote)
        return pending

    def get_supplier_quotes_for_part(self, part_number: str, include_pending: bool = True) -> List[SupplierQuote]:
        matches: List[SupplierQuote] = []
        for quotes in self.supplier_quotes.values():
            for quote in quotes:
                if quote.part_number == part_number:
                    if not include_pending and quote.status == "PENDING_SUPPLIER_RESPONSE":
                        continue
                    matches.append(quote)
        return matches

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

    def add_quote_item(self, quote_id: str, rfq_item_id: str, part_number: str, qty: int, source: str, unit_cost: float, unit_price: float, margin: float, cert: str, comp_status: str) -> QuoteItem:
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
            compliance_status=comp_status
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
