from __future__ import annotations

from typing import Any, Dict, Optional

from core.orchestrator.event_bus import SwarmEventBus
from core.policy_engine import AutonomousPolicyGate, QuotePayload
from schemas.events import SwarmEvent
from services.hitl_queue import HumanEscalationQueue


class PolicyEventHandler:
    """Evaluate aggregated results and route approval or HITL events."""

    def __init__(
        self,
        event_bus: SwarmEventBus,
        hitl_queue: HumanEscalationQueue,
        policy_gate: Optional[AutonomousPolicyGate] = None,
    ) -> None:
        self.event_bus = event_bus
        self.hitl_queue = hitl_queue
        self.policy_gate = policy_gate or AutonomousPolicyGate()
        event_bus.subscribe("event.quote.generated", self.handle)

    async def handle(self, event: SwarmEvent) -> None:
        payload = dict(event.payload)
        quote_data = payload.get("quote", payload)
        compliance_data = payload.get("compliance", {})
        quote_payload = QuotePayload.model_validate({
            **quote_data,
            "total_amount": quote_data.get(
                "total_amount", quote_data.get("total_quote_value_usd", 0.0)
            ),
            "extraction_confidence": payload.get(
                "extraction_confidence", quote_data.get("extraction_confidence", 0.0)
            ),
            "compliance_status": compliance_data.get(
                "compliance_status", quote_data.get("compliance_status", "HUMAN_REVIEW_REQUIRED")
            ),
            "sanctions_hits": compliance_data.get("sanctions_hits", quote_data.get("sanctions_hits", [])),
            "sanctions_clear": compliance_data.get("sanctions_clear", quote_data.get("sanctions_clear")),
        })
        decision = self.policy_gate.evaluate_auto_dispatch(quote_payload)
        decision_payload = {
            "can_auto_dispatch": decision.can_auto_dispatch,
            "escalation_reasons": decision.escalation_reasons,
            "quote_id": quote_data.get("quote_id"),
            "source_event_id": event.event_id,
        }
        decision_event = SwarmEvent(
            event_type="event.policy.decided",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:event.policy.decided",
            payload=decision_payload,
        )
        await self.event_bus.publish(decision_event)

        if decision.can_auto_dispatch:
            await self.event_bus.publish(SwarmEvent(
                event_type="event.auto_dispatch.approved",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.auto_dispatch.approved",
                payload=decision_payload,
            ))
        else:
            escalation = SwarmEvent(
                event_type="event.escalated.human",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:event.escalated.human",
                payload={
                    **decision_payload,
                    "reason": "; ".join(decision.escalation_reasons),
                },
            )
            await self.hitl_queue.enqueue(escalation)
            await self.event_bus.publish(escalation)


class DispatchSafetyHandler:
    """Terminal dispatch guard that prevents duplicate or unapproved sends."""

    def __init__(self, event_bus: SwarmEventBus) -> None:
        self.event_bus = event_bus
        self.dispatched_correlations: set[str] = set()
        event_bus.subscribe("event.auto_dispatch.approved", self.handle)

    async def handle(self, event: SwarmEvent) -> None:
        if event.correlation_id in self.dispatched_correlations:
            return
        quote_id = event.payload.get("quote_id")
        if not quote_id:
            await self.event_bus.publish(SwarmEvent(
                event_type="event.agent.failed",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:dispatch-missing-quote",
                payload={"agent_name": "DispatchSafetyHandler", "error": "quote_id is required"},
            ))
            return
        self.dispatched_correlations.add(event.correlation_id)
        await self.event_bus.publish(SwarmEvent(
            event_type="event.auto_dispatch.executed",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:event.auto_dispatch.executed",
            payload={"quote_id": quote_id, "status": "SIMULATED"},
        ))
