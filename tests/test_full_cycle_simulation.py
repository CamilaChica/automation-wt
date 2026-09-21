from __future__ import annotations

import asyncio

from agents.compliance_agent import ComplianceAgent
from core.orchestrator.event_bus import SwarmEventBus
from services.swarm_policy_runtime import DispatchSafetyHandler, PolicyEventHandler
from services.hitl_queue import HumanEscalationQueue
from schemas.events import SwarmEvent
from tests.simulators.clients import ClientSimulator
from tests.simulators.internal import InternalTeamSimulator
from tests.simulators.suppliers import FastTrackAeroParts, SanctionedFlagDistributor


def _wire_ingestion_and_sourcing(bus: SwarmEventBus) -> None:
    async def ingest(event: SwarmEvent) -> None:
        await bus.publish(SwarmEvent(
            event_type="event.rfq.extracted",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:rfq.extracted",
            payload={**event.payload, "extraction_confidence": 0.98},
        ))

    async def request_supplier(event: SwarmEvent) -> None:
        await bus.publish(SwarmEvent(
            event_type="event.sourcing.requested",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:sourcing.requested",
            payload=event.payload,
        ))

    bus.subscribe("event.rfq.received", ingest)
    bus.subscribe("event.rfq.extracted", request_supplier)


def test_full_cycle_urgent_aog_client_success():
    async def run():
        bus = SwarmEventBus()
        queue = HumanEscalationQueue()
        client = ClientSimulator("AOG Express Airlines", "CUST-AOG-01", bus)
        supplier = FastTrackAeroParts(bus)
        _wire_ingestion_and_sourcing(bus)
        bus.subscribe("event.sourcing.requested", supplier.handle_sourcing_request)

        async def quote_from_supplier(event: SwarmEvent) -> None:
            if event.payload["sanctions_hit"]:
                return
            await bus.publish(SwarmEvent(
                event_type="event.quote.generated",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:quote.generated",
                payload={
                    "quote_id": "Q-AOG-1",
                    "total_amount": 2500.0,
                    "gross_margin": 0.25,
                    "extraction_confidence": 0.98,
                    "compliance_status": "APPROVED",
                    "sanctions_clear": True,
                    "unit_sell_usd": 1250.0,
                },
            ))

        bus.subscribe("event.supplier.response", quote_from_supplier)
        PolicyEventHandler(bus, queue)
        DispatchSafetyHandler(bus)
        bus.subscribe("event.auto_dispatch.executed", client.handle_dispatch)

        await client.send_rfq("35-380004-3", 2, "URGENT AOG: need 2 units with FAA 8130-3", "AOG")

        assert len(client.received_quotes) == 1
        assert client.received_quotes[0]["quote_id"] == "Q-AOG-1"
        assert queue.qsize() == 0
        assert "event.auto_dispatch.executed" in [event.event_type for event in bus.get_history()]

    asyncio.run(run())


def test_full_cycle_bargain_client_counter_offer_escalates_to_sales_manager():
    async def run():
        bus = SwarmEventBus()
        queue = HumanEscalationQueue()
        client = ClientSimulator("Bargain MRO Purchaser", "CUST-DISCOUNT", bus)
        sales_manager = InternalTeamSimulator("Sales_Manager", bus)
        _wire_ingestion_and_sourcing(bus)
        bus.subscribe("event.quote.generated", client.handle_quote)

        async def negotiation_evaluator(event: SwarmEvent) -> None:
            requested = event.payload["target_price_usd"]
            margin = (requested - 1000.0) / requested
            if margin < 0.18:
                escalation = SwarmEvent(
                    event_type="event.escalated.human",
                    correlation_id=event.correlation_id,
                    idempotency_key=f"{event.event_id}:margin-escalation",
                    payload={"reason": "COUNTER_OFFER_MARGIN_TOO_LOW", "resulting_margin": margin},
                )
                await queue.enqueue(escalation)
                await bus.publish(escalation)

        bus.subscribe("event.client.counter_offer", negotiation_evaluator)
        bus.subscribe("event.escalated.human", sales_manager.handle_escalation)

        await bus.publish(SwarmEvent(
            event_type="event.quote.generated",
            correlation_id="corr-bargain",
            idempotency_key="quote-bargain",
            payload={"quote_id": "Q-BARGAIN-1", "unit_sell_usd": 1200.0},
        ))

        assert len(sales_manager.escalated_queue) == 1
        assert sales_manager.escalated_queue[0].payload["reason"] == "COUNTER_OFFER_MARGIN_TOO_LOW"
        escalation = await queue.dequeue(timeout=0.1)
        await sales_manager.approve_escalated_quote(escalation)
        assert "event.quote.approved_by_human" in [event.event_type for event in bus.get_history()]

    asyncio.run(run())


def test_full_cycle_sanctions_blocking_stops_outbound_communication():
    async def run():
        bus = SwarmEventBus()
        client = ClientSimulator("Foreign Commercial Airline", "CUST-FOREIGN", bus)
        supplier = SanctionedFlagDistributor(bus)
        compliance = ComplianceAgent()
        _wire_ingestion_and_sourcing(bus)
        bus.subscribe("event.sourcing.requested", supplier.handle_sourcing_request)
        bus.subscribe("event.auto_dispatch.executed", client.handle_dispatch)

        async def compliance_gate(event: SwarmEvent) -> None:
            result = await compliance.execute({
                "part_number": event.payload["part_number"],
                "source": "Supplier",
                "supplier_name": event.payload["supplier_name"],
                "certificate_type": event.payload["certificate_type"],
                "has_full_trace": True,
            })
            if not result.success or result.data["compliance_status"] == "REJECTED":
                await bus.publish(SwarmEvent(
                    event_type="event.compliance.flagged",
                    correlation_id=event.correlation_id,
                    idempotency_key=f"{event.event_id}:compliance.flagged",
                    payload={"reason": "SANCTIONS_MATCH_DETECTED", **result.data},
                ))
                return
            await bus.publish(SwarmEvent(
                event_type="event.quote.generated",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:quote.generated",
                payload={"quote_id": "Q-SAFE", "total_amount": 1000.0, "gross_margin": 0.25, "extraction_confidence": 0.98, "compliance_status": "APPROVED", "sanctions_clear": True},
            ))

        bus.subscribe("event.supplier.response", compliance_gate)
        await client.send_rfq("060-1234-00", 1, "Need one unit with certification.")

        event_types = [event.event_type for event in bus.get_history()]
        assert "event.compliance.flagged" in event_types
        assert "event.auto_dispatch.executed" not in event_types
        assert client.received_quotes == []

    asyncio.run(run())
