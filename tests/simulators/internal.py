from __future__ import annotations

from typing import List

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent


class InternalTeamSimulator:
    def __init__(self, role: str, event_bus: SwarmEventBus):
        self.role = role
        self.event_bus = event_bus
        self.escalated_queue: List[SwarmEvent] = []

    async def handle_escalation(self, event: SwarmEvent) -> None:
        self.escalated_queue.append(event)

    async def approve_escalated_quote(self, event: SwarmEvent) -> None:
        await self.event_bus.publish(SwarmEvent(
            event_type="event.quote.approved_by_human",
            correlation_id=event.correlation_id,
            idempotency_key=f"{event.event_id}:human-approval:{self.role}",
            payload={**event.payload, "approved_by": f"Human_{self.role}"},
        ))
