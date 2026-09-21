from __future__ import annotations

from typing import Any, Dict

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent


class SwarmRuntime:
    """Ingress runtime for shadow-mode event publication."""

    def __init__(self, event_bus: SwarmEventBus | None = None) -> None:
        self.event_bus = event_bus or SwarmEventBus()

    async def publish_rfq_received(
        self,
        rfq_id: str,
        raw_text: str,
        customer_id: str,
        customer_name: str,
        customer_email: str,
        thread_id: str | None = None,
    ) -> bool:
        return await self.event_bus.publish(
            SwarmEvent(
                event_type="event.rfq.received",
                correlation_id=rfq_id,
                idempotency_key=f"rfq.received:{rfq_id}",
                payload={
                    "rfq_id": rfq_id,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "raw_text": raw_text,
                    "thread_id": thread_id,
                },
            )
        )


swarm_runtime = SwarmRuntime()
