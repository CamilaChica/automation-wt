import asyncio

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent
from services.hitl_queue import HumanEscalationQueue
from services.swarm_policy_runtime import DispatchSafetyHandler, PolicyEventHandler


def test_policy_runtime_routes_clean_quote_to_dispatch():
    async def run():
        bus = SwarmEventBus()
        queue = HumanEscalationQueue()
        PolicyEventHandler(bus, queue)
        DispatchSafetyHandler(bus)
        executed = []

        async def capture(event):
            executed.append(event)

        bus.subscribe("event.auto_dispatch.executed", capture)
        await bus.publish(SwarmEvent(
            event_type="event.quote.generated",
            correlation_id="corr-clean",
            idempotency_key="quote-clean",
            payload={
                "quote_id": "Q-1",
                "total_amount": 1000.0,
                "gross_margin": 0.25,
                "extraction_confidence": 0.99,
                "compliance_status": "APPROVED",
                "sanctions_clear": True,
            },
        ))

        assert len(executed) == 1
        assert executed[0].payload["quote_id"] == "Q-1"
        assert queue.qsize() == 0

    asyncio.run(run())


def test_policy_runtime_routes_low_margin_to_hitl():
    async def run():
        bus = SwarmEventBus()
        queue = HumanEscalationQueue()
        PolicyEventHandler(bus, queue)
        await bus.publish(SwarmEvent(
            event_type="event.quote.generated",
            correlation_id="corr-risk",
            idempotency_key="quote-risk",
            payload={
                "quote_id": "Q-2",
                "total_amount": 1000.0,
                "gross_margin": 0.10,
                "extraction_confidence": 0.99,
                "compliance_status": "APPROVED",
                "sanctions_clear": True,
            },
        ))

        escalation = await queue.dequeue(timeout=0.1)
        assert escalation.event_type == "event.escalated.human"
        assert "gross margin" in escalation.payload["reason"]

    asyncio.run(run())