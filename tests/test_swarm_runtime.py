import asyncio

from core.orchestrator.event_bus import SwarmEventBus
from services.swarm_runtime import SwarmRuntime


def test_swarm_runtime_publishes_canonical_rfq_ingress():
    async def run():
        bus = SwarmEventBus()
        runtime = SwarmRuntime(bus)
        await runtime.publish_rfq_received(
            rfq_id="RFQ-SHADOW-1",
            raw_text="Part Number: PN-1 Qty: 1",
            customer_id="CUS-1",
            customer_name="Test MRO",
            customer_email="buyer@example.com",
        )
        event = bus.get_history()[0]
        assert event.event_type == "event.rfq.received"
        assert event.correlation_id == "RFQ-SHADOW-1"
        assert event.idempotency_key == "rfq.received:RFQ-SHADOW-1"
        assert event.payload["customer_email"] == "buyer@example.com"

    asyncio.run(run())
