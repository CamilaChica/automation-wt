import asyncio

from core.orchestrator.aggregation import CorrelationAggregator
from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent
from services.hitl_queue import HumanEscalationQueue


def test_correlation_aggregator_emits_once_after_all_inputs():
    async def run():
        bus = SwarmEventBus()
        aggregator = CorrelationAggregator(bus, {"inventory.done", "compliance.done"}, "inputs.ready")
        received = []

        async def capture(event):
            received.append(event)

        bus.subscribe("inputs.ready", capture)
        for event_type in ("inventory.done", "compliance.done"):
            await bus.publish(SwarmEvent(
                event_type=event_type,
                correlation_id="corr-1",
                idempotency_key=f"{event_type}:1",
                payload={"source": event_type},
            ))

        assert len(received) == 1
        assert set(received[0].payload["events"]) == {"inventory.done", "compliance.done"}
        assert aggregator is not None

    asyncio.run(run())


def test_hitl_queue_preserves_escalation_event():
    async def run():
        queue = HumanEscalationQueue()
        event = SwarmEvent(
            event_type="event.escalated.human",
            correlation_id="corr-2",
            idempotency_key="hitl-1",
            payload={"reason": "low margin"},
        )
        await queue.enqueue(event)
        assert queue.qsize() == 1
        assert await queue.dequeue(timeout=0.1) == event

    asyncio.run(run())
