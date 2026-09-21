from __future__ import annotations

import asyncio
from uuid import uuid4

from agents.compliance_agent import ComplianceAgent
from agents.pricing_agent import PricingAgent
from agents.supplier_discovery_agent import SupplierDiscoveryAgent
from core.orchestrator.event_bus import SwarmEventBus
from core.policy_engine import AutonomousPolicyGate, QuotePayload
from schemas.events import SwarmEvent
from tests.simulators.suppliers import (
    SupplierOEMFast,
    SupplierSlowUncertified,
    SupplierSurplusBudget,
)


def test_full_commercial_lifecycle():
    async def run():
        bus = SwarmEventBus()
        sourcing = SupplierDiscoveryAgent()
        compliance = ComplianceAgent()
        pricing = PricingAgent()
        policy = AutonomousPolicyGate()
        suppliers = [
            SupplierOEMFast(bus),
            SupplierSurplusBudget(bus),
            SupplierSlowUncertified(bus),
        ]
        audit_trail = []
        selected_vendor = {}
        final_quote = {}
        unhandled = []

        async def log_event(event: SwarmEvent):
            audit_trail.append(event.event_type)

        async def ingestion(event: SwarmEvent):
            await bus.publish(SwarmEvent(
                event_type="event.rfq.extracted",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:rfq.extracted",
                payload={**event.payload, "extraction_confidence": 0.98},
            ))

        async def broadcast(event: SwarmEvent):
            await bus.publish(SwarmEvent(
                event_type="event.supplier.rfq_broadcast",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:supplier.rfq_broadcast",
                payload={**event.payload, "expected_supplier_count": len(suppliers), "max_lead_time_days": 7},
            ))

        async def collect_quote(event: SwarmEvent):
            selected = await sourcing.handle_supplier_quote_received(event)
            if selected is None:
                return
            selected_vendor.update(selected)
            await bus.publish(SwarmEvent(
                event_type="event.supplier.vendor_selected",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:supplier.vendor_selected",
                payload={**selected, "quantity": 5, "customer_id": "CUST-DELTA-AERO", "extraction_confidence": 0.98},
            ))

        async def compliance_check(event: SwarmEvent):
            result = await compliance.execute({
                "part_number": event.payload["part_number"],
                "source": "Supplier",
                "supplier_name": event.payload["vendor_id"],
                "certificate_type": event.payload["certificate_type"],
                "has_full_trace": True,
            })
            assert result.success
            assert result.data["compliance_status"] == "APPROVED"
            await bus.publish(SwarmEvent(
                event_type="event.compliance.cleared",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:compliance.cleared",
                payload={**event.payload, "compliance_status": "APPROVED", "sanctions_clear": True},
            ))

        async def generate_quote(event: SwarmEvent):
            result = await pricing.execute({
                "unit_cost": event.payload["unit_cost"],
                "quantity": event.payload["quantity"],
                "source": "Supplier",
            })
            assert result.success
            margin = result.data["margin_percent"] / 100
            assert margin >= 0.18
            quote = {
                "quote_id": f"Q-{uuid4().hex[:8].upper()}",
                "rfq_id": event.payload["rfq_id"],
                "customer_id": event.payload["customer_id"],
                "part_number": event.payload["part_number"],
                "quantity": event.payload["quantity"],
                "unit_cost": result.data["unit_cost"],
                "unit_price": result.data["suggested_unit_price"],
                "gross_margin": margin,
                "total_amount": round(result.data["suggested_unit_price"] * event.payload["quantity"], 2),
                "extraction_confidence": event.payload["extraction_confidence"],
                "compliance_status": event.payload["compliance_status"],
                "sanctions_clear": event.payload["sanctions_clear"],
            }
            final_quote.update(quote)
            await bus.publish(SwarmEvent(
                event_type="event.quote.generated",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.quote.generated",
                payload=quote,
            ))

        async def policy_gate(event: SwarmEvent):
            decision = policy.evaluate_auto_dispatch(QuotePayload.model_validate(event.payload))
            assert decision.can_auto_dispatch
            await bus.publish(SwarmEvent(
                event_type="event.quote.dispatched",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.quote.dispatched",
                payload={**event.payload, "policy_approved": True},
            ))

        async def client_accepts_quote(event: SwarmEvent):
            await bus.publish(SwarmEvent(
                event_type="event.client.po_submitted",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.client.po_submitted",
                payload={"quote_id": event.payload["quote_id"], "po_number": "PO-DELTA-100", "customer_id": event.payload["customer_id"]},
            ))

        async def close_order(event: SwarmEvent):
            await bus.publish(SwarmEvent(
                event_type="event.order.confirmed",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.order.confirmed",
                payload={"quote_id": event.payload["quote_id"], "po_number": event.payload["po_number"], "status": "CONFIRMED"},
            ))

        async def capture_failure(event: SwarmEvent):
            unhandled.append(event.payload)

        for event_type in (
            "event.rfq.received", "event.rfq.extracted", "event.supplier.rfq_broadcast",
            "event.supplier.quote_received", "event.supplier.vendor_selected", "event.compliance.cleared",
            "event.quote.generated", "event.quote.dispatched", "event.client.po_submitted", "event.order.confirmed",
        ):
            bus.subscribe(event_type, log_event)
        bus.subscribe("event.rfq.received", ingestion)
        bus.subscribe("event.rfq.extracted", broadcast)
        bus.subscribe("event.supplier.rfq_broadcast", sourcing.handle_supplier_rfq_broadcast)
        for supplier in suppliers:
            bus.subscribe("event.supplier.rfq_broadcast", supplier.handle_supplier_broadcast)
        bus.subscribe("event.supplier.quote_received", collect_quote)
        bus.subscribe("event.supplier.vendor_selected", compliance_check)
        bus.subscribe("event.compliance.cleared", generate_quote)
        bus.subscribe("event.quote.generated", policy_gate)
        bus.subscribe("event.quote.dispatched", client_accepts_quote)
        bus.subscribe("event.client.po_submitted", close_order)
        bus.subscribe("event.agent.failed", capture_failure)

        correlation_id = f"COMMERCIAL-CYCLE-{uuid4().hex[:8]}"
        await bus.publish(SwarmEvent(
            event_type="event.rfq.received",
            correlation_id=correlation_id,
            idempotency_key=f"{correlation_id}:event.rfq.received",
            payload={
                "rfq_id": "RFQ-COMM-100",
                "customer_id": "CUST-DELTA-AERO",
                "part_number": "35-380004-3",
                "quantity": 5,
                "required_cert": "FAA_8130_3",
                "max_lead_time_days": 7,
                "target_price": 1800.0,
            },
        ))

        assert selected_vendor["vendor_id"] in {"OEM-FAST", "SURPLUS-BUDGET"}
        assert selected_vendor["vendor_id"] != "SLOW-UNCERTIFIED"
        assert selected_vendor["quantity_available"] >= 5
        assert selected_vendor["lead_time_days"] <= 7
        assert final_quote["gross_margin"] >= 0.18
        assert final_quote["total_amount"] <= 25000
        assert audit_trail[:3] == ["event.rfq.received", "event.rfq.extracted", "event.supplier.rfq_broadcast"]
        assert "event.supplier.vendor_selected" in audit_trail
        assert "event.compliance.cleared" in audit_trail
        assert "event.quote.generated" in audit_trail
        assert "event.quote.dispatched" in audit_trail
        assert "event.client.po_submitted" in audit_trail
        assert "event.order.confirmed" in audit_trail
        assert not unhandled
        assert not bus.get_failed_handlers()

    asyncio.run(run())
