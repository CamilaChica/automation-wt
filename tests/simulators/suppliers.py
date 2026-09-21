from __future__ import annotations

from typing import Any, Dict

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent


class SupplierSimulator:
    def __init__(self, name: str, event_bus: SwarmEventBus, sanctioned: bool = False):
        self.name = name
        self.event_bus = event_bus
        self.sanctioned = sanctioned

    async def handle_sourcing_request(self, event: SwarmEvent) -> None:
        await self.event_bus.publish(SwarmEvent(
            event_type="event.supplier.response",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:supplier-response:{self.name}",
            payload={
                "supplier_name": self.name,
                "part_number": event.payload.get("part_number", "060-1234-00"),
                "quantity_available": event.payload.get("quantity", 1),
                "unit_cost": 1000.0,
                "lead_time_days": 1,
                "certificate_type": "FAA 8130-3",
                "sanctions_hit": self.sanctioned,
            },
        ))


class FastTrackAeroParts(SupplierSimulator):
    def __init__(self, event_bus: SwarmEventBus):
        super().__init__("FastTrack Aero Parts", event_bus)


class SanctionedFlagDistributor(SupplierSimulator):
    def __init__(self, event_bus: SwarmEventBus):
        super().__init__("Sanctioned Flag Distributor", event_bus, sanctioned=True)


class CommercialSupplierSimulator(SupplierSimulator):
    def __init__(self, name: str, event_bus: SwarmEventBus, quote: Dict[str, Any]):
        super().__init__(name, event_bus)
        self.quote = quote

    async def handle_supplier_broadcast(self, event: SwarmEvent) -> None:
        await self.event_bus.publish(SwarmEvent(
            event_type="event.supplier.quote_received",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:quote:{self.name}",
            payload={
                **self.quote,
                "rfq_id": event.payload["rfq_id"],
                "part_number": event.payload["part_number"],
                "quantity_available": self.quote.get("quantity_available", event.payload["quantity"]),
                "expected_supplier_count": event.payload.get("expected_supplier_count", 3),
                "max_lead_time_days": event.payload.get("max_lead_time_days"),
            },
        ))


class SupplierOEMFast(CommercialSupplierSimulator):
    def __init__(self, event_bus: SwarmEventBus):
        super().__init__("Supplier_OEM_Fast", event_bus, {
            "vendor_id": "OEM-FAST",
            "unit_cost": 1500.0,
            "lead_time_days": 1,
            "certificate_type": "FAA 8130-3",
            "vendor_rating": 0.98,
            "quantity_available": 100,
        })


class SupplierSurplusBudget(CommercialSupplierSimulator):
    def __init__(self, event_bus: SwarmEventBus):
        super().__init__("Supplier_Surplus_Budget", event_bus, {
            "vendor_id": "SURPLUS-BUDGET",
            "unit_cost": 1100.0,
            "lead_time_days": 5,
            "certificate_type": "OEM Trace",
            "vendor_rating": 0.90,
            "quantity_available": 5,
        })


class SupplierSlowUncertified(CommercialSupplierSimulator):
    def __init__(self, event_bus: SwarmEventBus):
        super().__init__("Supplier_Slow_Uncertified", event_bus, {
            "vendor_id": "SLOW-UNCERTIFIED",
            "unit_cost": 800.0,
            "lead_time_days": 14,
            "certificate_type": "None",
            "vendor_rating": 0.95,
            "quantity_available": 100,
        })
