from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.customer_communication_agent import CustomerCommunicationAgent, GeneratedEmailDraft


class TestCustomerCommunicationPolicy(unittest.TestCase):
    def test_company_name_is_grounded_and_email_policy_is_enforced(self):
        router = Mock()
        router.task_providers = {"customer_communication": "test"}
        router.providers = {"test": object()}
        router.extract_structured_with_response.return_value = (
            GeneratedEmailDraft(
                subject="Quotation QTE-9921",
                body_text=(
                    "Dear Maria Buyer,\n\n"
                    "Your quotation is ready.\n\nBest regards,\nSales Team"
                ),
                body_html="<p>Your quotation is ready.</p>",
                confidence_score=0.9,
            ),
            SimpleNamespace(provider="test", model="test-model", raw={"usage": {}}),
        )
        agent = CustomerCommunicationAgent(llm_router=router)

        result = asyncio.run(agent.execute(
            {
                "customer_email": "buyer@global.example",
                "customer_name": "Maria Buyer",
                "company_name": "Global Airlines",
                "quote_details": {"quote_id": "QTE-9921", "items": []},
            },
            context={"draft_only": True},
        ))

        self.assertTrue(result.success, result.error_message)
        user_prompt = router.extract_structured_with_response.call_args.args[0].user_prompt
        prompt_data = json.loads(user_prompt)["untrusted_quote_data"]
        self.assertEqual(
            prompt_data["company_name_from_portal_or_verified_communication"],
            "Global Airlines",
        )
        body = result.data["formatted_body"]
        self.assertTrue(body.startswith("Hi Global Airlines,\n\n"))
        self.assertIn("Does this quotation meet your needs?", body)
        self.assertIn("https://portal.wingedtycoons.com/customer-portal", body)

    def test_dispatched_result_reports_the_rendered_email_not_the_llm_draft(self):
        router = Mock()
        router.task_providers = {"customer_communication": "test"}
        router.providers = {"test": object()}
        router.extract_structured_with_response.return_value = (
            GeneratedEmailDraft(
                subject="LLM draft subject",
                body_text="This is only the LLM draft body.",
                body_html="<p>This is only the LLM draft body.</p>",
                confidence_score=0.9,
            ),
            SimpleNamespace(provider="test", model="test-model", raw={"usage": {}}),
        )
        agent = CustomerCommunicationAgent(llm_router=router)
        dispatched = {
            "transmission_status": "QUEUED",
            "rendered_subject": "Winged Tycoons quotation QTE-9921",
            "rendered_body": "The deterministic quote email that was actually queued.",
            "rendered_html_body": "<p>The deterministic quote email that was actually queued.</p>",
        }

        with (
            patch.object(agent, "_format_quote_summary", return_value="Approved quote"),
            patch(
                "agents.customer_communication_agent.communication_service.send_customer_quote",
                return_value=dispatched,
            ),
            patch("agents.customer_communication_agent.operations_store.record_llm_telemetry"),
            patch("agents.customer_communication_agent.operations_store.record_automation_event"),
        ):
            result = asyncio.run(agent.execute({
                "customer_email": "buyer@global.example",
                "customer_name": "Maria Buyer",
                "company_name": "Global Airlines",
                "quote_details": {"quote_id": "QTE-9921", "items": []},
            }))

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.data["subject"], dispatched["rendered_subject"])
        self.assertEqual(result.data["formatted_body"], dispatched["rendered_body"])
        self.assertEqual(result.data["body_html"], dispatched["rendered_html_body"])


if __name__ == "__main__":
    unittest.main()
