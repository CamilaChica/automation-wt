from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent


class ClientSimulator:
    def __init__(self, name: str, client_id: str, event_bus: SwarmEventBus):
        self.name = name
        self.client_id = client_id
        self.event_bus = event_bus
        self.received_quotes: List[Dict[str, Any]] = []
        self.received_events: List[SwarmEvent] = []

    async def send_rfq(self, part_number: str, quantity: int, raw_text: str, urgency: str = "STANDARD") -> str:
        correlation_id = f"SIM-{uuid4().hex[:8]}"
        await self.event_bus.publish(SwarmEvent(
            event_type="event.rfq.received",
            correlation_id=correlation_id,
            idempotency_key=f"{correlation_id}:rfq.received",
            payload={
                "rfq_id": f"RFQ-{uuid4().hex[:8].upper()}",
                "customer_id": self.client_id,
                "customer_name": self.name,
                "part_number": part_number,
                "quantity": quantity,
                "urgency": urgency,
                "raw_text": raw_text,
            },
        ))
        return correlation_id

    async def handle_dispatch(self, event: SwarmEvent) -> None:
        self.received_events.append(event)
        self.received_quotes.append(dict(event.payload))

    async def handle_quote(self, event: SwarmEvent) -> None:
        self.received_events.append(event)
        self.received_quotes.append(dict(event.payload))
        if "Bargain" in self.name:
            unit_price = float(event.payload.get("unit_price_usd", event.payload.get("unit_sell_usd", 0)))
            await self.event_bus.publish(SwarmEvent(
                event_type="event.client.counter_offer",
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.event_id}:counter-offer",
                payload={
                    "quote_id": event.payload.get("quote_id"),
                    "customer_id": self.client_id,
                    "target_price_usd": round(unit_price * 0.85, 2),
                    "reason": "Competitor offered a lower price.",
                },
            ))
