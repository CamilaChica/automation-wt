import asyncio
import json
import unittest
from unittest.mock import patch

from services.communication_service import CommunicationService
from services.llm_provider import LLMProvider, LLMResponse, LLMRouter
from agents.customer_communication_agent import CustomerCommunicationAgent


class FakeCommunicationProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            provider=self.name,
            model="test-model",
            text=json.dumps({
                "subject": "Quotation QTE-1001",
                "body_text": "Dear Buyer, your approved quotation is ready for review.",
                "body_html": "<p>Your approved quotation is ready for review.</p>",
                "redacted_fields_applied": ["supplier costs", "internal margins"],
                "confidence_score": 0.98,
            }),
            raw={"usage": {"prompt_tokens": 100, "completion_tokens": 40}},
        )


class AutonomousSalesAndPoTests(unittest.TestCase):
    def test_customer_quote_invokes_llm_and_dispatches_without_approval(self):
        provider = FakeCommunicationProvider()
        agent = CustomerCommunicationAgent(LLMRouter({"openai": provider}))

        with patch.object(
            agent, "llm_router",
            LLMRouter({"openai": provider}),
        ), patch.object(
            __import__("agents.customer_communication_agent", fromlist=["communication_service"]).communication_service,
            "send_customer_quote",
            return_value={"transmission_status": "DRY_RUN"},
        ) as send_quote:
            result = asyncio.run(agent.execute({
                "customer_email": "buyer@example.com",
                "customer_name": "Buyer",
                "quote_details": {
                    "quote_id": "QTE-1001",
                    "subtotal": 1000,
                    "total_amount": 1100,
                    "quantity_defaulted": True,
                    "items": [{"part_number": "PN-1", "quantity": 2, "unit_price": 500}],
                },
            }))

        self.assertTrue(result.success)
        self.assertFalse(result.data["llm_fallback_used"])
        self.assertEqual(provider.requests[0].task, "customer_communication")
        self.assertIn("How many do you need?", provider.requests[0].system_prompt)
        send_quote.assert_called_once()
        self.assertEqual(send_quote.call_args.kwargs["subject_override"], "Quotation QTE-1001")

    def test_po_notification_is_actionable_and_human_gated(self):
        service = CommunicationService()
        with patch.object(service, "_send", return_value={"transmission_status": "DRY_RUN"}) as send:
            service.notify_purchase_order(
                recipient="camila@wingedtycoons.com",
                po_number="PO-1001",
                customer_name="Buyer Company",
                customer_email="buyer@example.com",
                quote_id="QTE-1001",
                review_url="https://rfq.wingedtycoons.com/?view=sales",
                items=[{"part_number": "PN-1", "quantity": 2, "unit_price": 500, "supplier_unit_cost": 300}],
            )

        subject = send.call_args.args[2]
        body = send.call_args.args[3]
        self.assertEqual(subject, "[ACTION REQUIRED] New Purchase Order Received - PO #PO-1001")
        self.assertIn("Total value: $1,000.00", body)
        self.assertIn("https://rfq.wingedtycoons.com/?view=sales", body)
        self.assertIn("Do not fulfill, invoice, or contact suppliers", body)


if __name__ == "__main__":
    unittest.main()