from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from agents.customer_communication_agent import CustomerCommunicationAgent, GeneratedEmailDraft
from services.email_intelligence import CommunicationSentiment, analyze_communication_sentiment
from services.email_templates import SupplierDiscountData, supplier_discount_request


class CommunicationSentimentTests(unittest.TestCase):
    def test_sentiment_analysis_is_structured_and_evidence_is_source_grounded(self):
        router = Mock()
        router.extract_structured_with_response.return_value = (
            CommunicationSentiment(
                label="negative",
                confidence=0.93,
                evidence=["The delivery delay is unacceptable.", "invented evidence"],
            ),
            Mock(provider="test", model="test-model", raw={}),
        )
        source = "The delivery delay is unacceptable. Please advise."

        result = analyze_communication_sentiment(source, router=router)

        self.assertEqual(result.label, "negative")
        self.assertEqual(result.evidence, ["The delivery delay is unacceptable."])
        request = router.extract_structured_with_response.call_args.args[0]
        self.assertIn("untrusted_content", json.loads(request.user_prompt))
        self.assertIn("Do not infer urgency", request.system_prompt)

    def test_sentiment_analysis_is_optional_when_live_llm_is_disabled(self):
        with patch.dict("os.environ", {"LLM_LIVE_ENABLED": "false"}):
            self.assertIsNone(analyze_communication_sentiment("Please send the quote."))

    def test_customer_draft_receives_sentiment_only_as_tone_guidance(self):
        router = Mock()
        router.task_providers = {"customer_communication": "test"}
        router.providers = {"test": object()}
        router.extract_structured_with_response.return_value = (
            GeneratedEmailDraft(
                subject="Quotation QTE-9912",
                body_text="Your quotation is ready.\n\nBest regards,\nSales Team",
                body_html="<p>Your quotation is ready.</p>",
                confidence_score=0.9,
            ),
            Mock(provider="test", model="test-model", raw={"usage": {}}),
        )
        agent = CustomerCommunicationAgent(llm_router=router)

        result = __import__("asyncio").run(agent.execute({
            "customer_email": "buyer@example.test",
            "customer_name": "Example Aerospace",
            "company_name": "Example Aerospace",
            "communication_sentiment": {
                "label": "negative",
                "confidence": 0.91,
                "evidence": ["The delay is unacceptable."],
            },
            "quote_details": {"quote_id": "QTE-9912", "items": []},
        }, context={"draft_only": True}))

        self.assertTrue(result.success, result.error_message)
        request = router.extract_structured_with_response.call_args.args[0]
        prompt_data = json.loads(request.user_prompt)["untrusted_quote_data"]
        self.assertEqual(prompt_data["communication_sentiment"]["label"], "negative")
        self.assertNotIn("The delay is unacceptable.", request.user_prompt)
        self.assertIn("empathetic and calm", request.system_prompt)

    def test_supplier_discount_tone_adjusts_without_changing_commercial_terms(self):
        data = SupplierDiscountData(
            supplier_contact="Supplier Team",
            recipient_email="quotes@example.test",
            part_number="060-1234-00",
            quantity=2,
            quoted_price=125.0,
            supplier_sentiment="negative",
        )

        message = supplier_discount_request(data).body

        self.assertIn("Thank you for clarifying your position", message)
        self.assertIn("$125.00", message)
        self.assertIn("best commercial price", message)


if __name__ == "__main__":
    unittest.main()
