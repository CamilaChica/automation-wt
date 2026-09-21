from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from agents.base_agent import BaseAgent
from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent


class AgentEventAdapter:
    """Translate an existing agent response into a canonical swarm event."""

    def __init__(
        self,
        agent: BaseAgent,
        event_bus: SwarmEventBus,
        input_event_type: str,
        output_event_type: str,
        input_mapper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.agent = agent
        self.event_bus = event_bus
        self.input_event_type = input_event_type
        self.output_event_type = output_event_type
        self.input_mapper = input_mapper or (lambda payload: payload)
        event_bus.subscribe(input_event_type, self.handle)

    async def handle(self, event: SwarmEvent) -> None:
        try:
            inputs = self.input_mapper(event.payload)
            response = await self.agent.execute(inputs)
            event_type = self.output_event_type if response.success else "event.agent.failed"
            payload = dict(response.data)
            payload["_agent"] = self.agent.metadata.name
            payload["_source_event_id"] = event.event_id
            payload["_escalation"] = (
                response.escalation_triggered.model_dump(mode="json")
                if response.escalation_triggered
                else None
            )
            await self.event_bus.publish(
                SwarmEvent(
                    event_type=event_type,
                    correlation_id=event.correlation_id,
                    idempotency_key=f"{event.event_id}:{event_type}:{self.agent.metadata.name}",
                    payload=payload,
                )
            )
        except Exception as exc:
            await self.event_bus.publish(
                SwarmEvent(
                    event_type="event.agent.failed",
                    correlation_id=event.correlation_id,
                    idempotency_key=f"{event.event_id}:event.agent.failed:{self.agent.metadata.name}",
                    payload={
                        "agent_name": self.agent.metadata.name,
                        "source_event_id": event.event_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            )


def wire_default_adapters(event_bus: SwarmEventBus) -> Dict[str, AgentEventAdapter]:
    """Wire the current agents into the first event-driven migration slice."""
    from agents.compliance_agent import ComplianceAgent
    from agents.customer_communication_agent import CustomerCommunicationAgent
    from agents.inventory_agent import InventoryAgent
    from agents.parts_intelligence_agent import PartsIntelligenceAgent
    from agents.pricing_agent import PricingAgent
    from agents.quote_generation_agent import QuoteGenerationAgent
    from agents.rfq_intake_agent import RFQIntakeAgent
    from agents.supplier_discovery_agent import SupplierDiscoveryAgent

    adapters = [
        AgentEventAdapter(RFQIntakeAgent(), event_bus, "event.rfq.received", "event.rfq.extracted"),
        AgentEventAdapter(PartsIntelligenceAgent(), event_bus, "event.rfq.extracted", "event.parts.validated"),
        AgentEventAdapter(InventoryAgent(), event_bus, "event.parts.validated", "event.inventory.completed"),
        AgentEventAdapter(SupplierDiscoveryAgent(), event_bus, "event.inventory.shortage", "event.sourcing.completed"),
        AgentEventAdapter(ComplianceAgent(), event_bus, "event.sourcing.completed", "event.compliance.completed"),
        AgentEventAdapter(PricingAgent(), event_bus, "event.compliance.completed", "event.quote.priced"),
        AgentEventAdapter(QuoteGenerationAgent(), event_bus, "event.quote.priced", "event.quote.generated"),
        AgentEventAdapter(CustomerCommunicationAgent(), event_bus, "event.quote.approved", "event.customer.communication"),
    ]
    return {adapter.agent.metadata.name: adapter for adapter in adapters}
