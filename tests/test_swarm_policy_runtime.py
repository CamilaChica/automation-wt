import asyncio
from unittest.mock import AsyncMock, Mock, patch

from core.orchestrator.event_bus import SwarmEventBus
from schemas.events import SwarmEvent
from schemas.extraction import PolicyEvaluationRecommendation
from services.hitl_queue import HumanEscalationQueue
from services.llm_provider import LLMResponse
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


def test_policy_advisory_cannot_override_backend_dispatch_gate():
    async def run():
        bus = Mock()
        bus.publish = AsyncMock()
        queue = Mock()
        queue.enqueue = AsyncMock()
        router = Mock()
        router.extract_structured_with_response.return_value = (
            PolicyEvaluationRecommendation(
                decision="approve",
                rationale="Advisory only.",
                policy_keys=["automatic_quote_dispatch"],
                confidence=0.9,
            ),
            LLMResponse("openai", "test-model", "{}", {}),
        )
        handler = PolicyEventHandler(bus, queue, llm_router=router)

        with patch.dict("os.environ", {"DSPY_ENABLED": "true"}):
            await handler.handle(SwarmEvent(
                event_type="event.quote.generated",
                correlation_id="corr-advisory",
                idempotency_key="quote-advisory",
                payload={
                    "quote_id": "Q-3",
                    "total_amount": 1000.0,
                    "gross_margin": 0.10,
                    "extraction_confidence": 0.99,
                    "compliance_status": "APPROVED",
                    "sanctions_clear": True,
                },
            ))

        published = [call.args[0] for call in bus.publish.await_args_list]
        decision_event = next(event for event in published if event.event_type == "event.policy.decided")
        assert decision_event.payload["can_auto_dispatch"] is False
        assert decision_event.payload["advisory_policy_recommendation"]["decision"] == "approve"
        assert not any(event.event_type == "event.auto_dispatch.approved" for event in published)
        queue.enqueue.assert_awaited_once()

    asyncio.run(run())