import asyncio

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent
from schemas.payloads import ConditionCode, ExtractedRFQPayload


def test_event_bus_deduplicates_and_fans_out():
    async def run():
        bus = SwarmEventBus()
        seen = []

        async def first(event):
            await asyncio.sleep(0)
            seen.append("first")

        async def second(event):
            seen.append("second")

        bus.subscribe("event.test", first)
        bus.subscribe("event.test", second)
        event = SwarmEvent(
            event_type="event.test",
            correlation_id="corr-1",
            idempotency_key="event-1",
            payload={"value": 1},
        )

        assert await bus.publish(event) is True
        assert await bus.publish(event) is False
        assert sorted(seen) == ["first", "second"]
        assert len(bus.get_history()) == 1

    asyncio.run(run())


def test_domain_payload_is_frozen_and_validated():
    payload = ExtractedRFQPayload(
        rfq_id="RFQ-1",
        customer_id="CUST-1",
        part_number="PN-1",
        quantity=2,
        condition=ConditionCode.NE,
        extraction_confidence=0.98,
    )

    try:
        payload.quantity = 3
    except Exception:
        pass
    else:
        raise AssertionError("canonical payload must be immutable")
