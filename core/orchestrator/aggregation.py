from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, Iterable, List

from schemas.events import SwarmEvent
from core.orchestrator.event_bus import SwarmEventBus


class CorrelationAggregator:
    """Join required events for a correlation ID before advancing the workflow."""

    def __init__(
        self,
        event_bus: SwarmEventBus,
        input_event_types: Iterable[str],
        output_event_type: str,
    ) -> None:
        self.event_bus = event_bus
        self.input_event_types = frozenset(input_event_types)
        self.output_event_type = output_event_type
        self._events: Dict[str, Dict[str, SwarmEvent]] = defaultdict(dict)
        self._emitted: set[str] = set()
        self._lock = asyncio.Lock()
        for event_type in self.input_event_types:
            event_bus.subscribe(event_type, self.handle)

    async def handle(self, event: SwarmEvent) -> None:
        async with self._lock:
            correlation_events = self._events[event.correlation_id]
            correlation_events[event.event_type] = event
            if correlation_events.keys() < self.input_event_types:
                return
            if event.correlation_id in self._emitted:
                return
            self._emitted.add(event.correlation_id)
            events = dict(correlation_events)

        await self.event_bus.publish(
            SwarmEvent(
                event_type=self.output_event_type,
                correlation_id=event.correlation_id,
                idempotency_key=f"{event.correlation_id}:{self.output_event_type}",
                payload={
                    "correlation_id": event.correlation_id,
                    "events": {event_type: value.payload for event_type, value in events.items()},
                    "source_event_ids": {event_type: value.event_id for event_type, value in events.items()},
                },
            )
        )

    def clear(self, correlation_id: str) -> None:
        self._events.pop(correlation_id, None)
        self._emitted.discard(correlation_id)
